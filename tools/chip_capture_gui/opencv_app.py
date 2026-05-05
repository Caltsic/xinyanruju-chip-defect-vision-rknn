from __future__ import annotations

import argparse
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2

from tools.adb_imx415_rknn_live_view import (
    CHIP_DEFECT_SEG_REMOTE_MODEL,
    CHIP_REMOTE_MODEL,
    CHIP_TWO_STAGE_CLASSES,
    Detection,
    draw_detections,
    filter_display_detections,
)
from tools.chip_roi_utils import clamp_box, draw_chip_box, expand_box, locate_chip_dark_edge

from .camera import RknnCamera, create_camera, format_stream_error, write_input_adjust_config
from .image_adjust import apply_adjustments
from .models import CameraFrame
from .settings import DEFAULT_OUTPUT_DIR, CameraSettings, ImageAdjustSettings, LightSettings
from .storage import CaptureStorage, ChipRoiRecord
from .ws2812 import create_ws2812_controller


DELETE_KEYS = {255, 3014656, 65535}
ENTER_KEYS = {10, 13}
QUIT_KEYS = {27, ord("q"), ord("Q")}


@dataclass(slots=True)
class RoiReviewState:
    record: ChipRoiRecord
    clean_bgr: object
    box: tuple[int, int, int, int] | None
    capture_adjusted: bool


@dataclass(slots=True)
class AdjustTarget:
    name: str
    step: float


ADJUST_TARGETS = [
    AdjustTarget("brightness", 1.0),
    AdjustTarget("contrast", 0.05),
    AdjustTarget("gamma", 0.03),
    AdjustTarget("saturation", 0.05),
    AdjustTarget("sharpness", 0.05),
    AdjustTarget("light", 0.05),
]


class OpenCvChipCaptureApp:
    def __init__(
        self,
        camera_settings: CameraSettings,
        image_settings: ImageAdjustSettings,
        light_settings: LightSettings,
        output_dir: Path,
        prefix: str,
        window_name: str,
        screen_width: int,
        screen_height: int,
        window_x: int,
        window_y: int,
        fullscreen: bool,
    ) -> None:
        self.camera_settings = camera_settings
        self.image_settings = image_settings
        self.light_settings = light_settings
        self.storage = CaptureStorage(output_dir)
        self.prefix = prefix
        self.window_name = window_name
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.window_x = window_x
        self.window_y = window_y
        self.fullscreen = fullscreen
        self.class_names = list(CHIP_TWO_STAGE_CLASSES)
        self.camera: RknnCamera | None = None
        self.light_controller = create_ws2812_controller(camera_settings, light_settings)
        self.last_frame: CameraFrame | None = None
        self.last_clean_bgr = None
        self.live_overlay_enabled = True
        self.review_state: RoiReviewState | None = None
        self.adjust_index = 0
        self.status = "starting"
        self.drawn_count = 0

    def run(self) -> int:
        self._prepare_display_env()
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        if self.fullscreen:
            cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        elif self.screen_width > 0 and self.screen_height > 0:
            cv2.resizeWindow(self.window_name, self.screen_width, self.screen_height)
            cv2.moveWindow(self.window_name, self.window_x, self.window_y)

        exit_code = 0
        try:
            self._start_runtime()
            while True:
                frame = self._read_frame()
                if frame is None:
                    break
                shown = self._render_review() if self.review_state is not None else self._render_live(frame)
                cv2.imshow(self.window_name, self._fit_to_screen(shown))
                key = cv2.waitKey(1) & 0xFFFFFF
                if key != 0xFFFFFF and self._handle_key(key):
                    break
        except KeyboardInterrupt:
            self.status = "interrupted"
        except Exception as exc:  # noqa: BLE001 - top-level GUI diagnostic
            print(format_stream_error(self.camera, exc) if self.camera is not None else str(exc), file=sys.stderr)
            exit_code = 2
        finally:
            if self.camera is not None:
                self.camera.stop()
                self.camera = None
            try:
                self.light_controller.off()
            except Exception:
                pass
            cv2.destroyAllWindows()
        return exit_code

    def _prepare_display_env(self) -> None:
        if self.camera_settings.backend != "local" or platform.system().lower().startswith("win"):
            return
        os.environ.setdefault("DISPLAY", ":0")
        if "XAUTHORITY" not in os.environ and Path("/var/run/lightdm/root/:0").exists():
            os.environ["XAUTHORITY"] = "/var/run/lightdm/root/:0"
        if "QT_QPA_FONTDIR" not in os.environ and Path("/usr/share/fonts/truetype/dejavu").exists():
            os.environ["QT_QPA_FONTDIR"] = "/usr/share/fonts/truetype/dejavu"

    def _start_runtime(self) -> None:
        self._sync_input_adjust_settings()
        self._write_input_adjust()
        try:
            self.light_controller.set_brightness(self.light_settings.brightness)
        except Exception as exc:  # noqa: BLE001 - display can still run without light control
            self.status = f"light failed: {exc}"

        self.camera = create_camera(self.camera_settings)
        checks = self.camera.preflight()
        missing_required = [name for name in ("camera", "stream") if not checks.get(name)]
        if missing_required:
            raise RuntimeError(f"preflight failed: {', '.join(missing_required)}")
        self.camera.start()
        self.status = "running"

    def _read_frame(self) -> CameraFrame | None:
        if self.camera is None:
            raise RuntimeError("camera is not running")
        frame = self.camera.read_frame()
        if frame is None:
            if self.camera.frames_seen == 0:
                raise RuntimeError(format_stream_error(self.camera) or "no frames")
            return None
        self.last_frame = frame
        self.last_clean_bgr = frame.clean_bgr.copy()
        return frame

    def _render_live(self, frame: CameraFrame):
        preview_bgr = frame.clean_bgr.copy() if self.camera_settings.input_adjust else apply_adjustments(frame.clean_bgr, self.image_settings)
        annotated_bgr = preview_bgr.copy()
        display_detections = filter_display_detections(
            frame.detections,
            frame.width,
            frame.height,
            self.camera_settings.to_namespace(),
        )
        if self.live_overlay_enabled:
            self.drawn_count = draw_detections(annotated_bgr, display_detections, self.class_names)
        else:
            self.drawn_count = 0
        self._draw_hud(annotated_bgr, frame, len(frame.detections), self.drawn_count)
        return annotated_bgr

    def _render_review(self):
        if self.review_state is None:
            raise RuntimeError("review is not active")
        preview_bgr = (
            self.review_state.clean_bgr.copy()
            if self.review_state.capture_adjusted
            else apply_adjustments(self.review_state.clean_bgr, self.image_settings)
        )
        text = f"{self.review_state.record.stem} | WASD move | +/- scale | Enter accept | Del/N negative"
        shown = draw_chip_box(preview_bgr, self.review_state.box, text, color=(70, 255, 150))
        self._draw_text_lines(
            shown,
            [
                "REVIEW",
                f"box={self.review_state.box if self.review_state.box else 'none'}",
                self.status,
            ],
            origin=(10, 42),
        )
        return shown

    def _draw_hud(self, image, frame: CameraFrame, raw_count: int, drawn_count: int) -> None:
        selected = ADJUST_TARGETS[self.adjust_index].name
        lines = [
            f"{self.camera_settings.backend.upper()} | FPS {frame.fps:.1f} | focus {frame.focus:.0f} | det {raw_count}/{drawn_count} | frame {frame.frame_index}",
            f"Bri {self.image_settings.brightness:+d}  C {self.image_settings.contrast:.2f}  G {self.image_settings.gamma:.2f}  Sat {self.image_settings.saturation:.2f}  Sharp {self.image_settings.sharpness:.2f}  Light {self.light_settings.brightness:.2f}",
            f"selected={selected}  Tab select  +/- adjust  1 Pins  2 Text  3 Damage  0 Reset  C capture  O overlay  I sync  Q quit",
            self.status,
        ]
        self._draw_text_lines(image, lines, origin=(10, 24))

    def _draw_text_lines(self, image, lines: list[str], origin: tuple[int, int]) -> None:
        x, y = origin
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.55
        thickness = 1
        line_h = 22
        max_w = 0
        for line in lines:
            size, _ = cv2.getTextSize(line, font, scale, thickness + 1)
            max_w = max(max_w, size[0])
        cv2.rectangle(image, (x - 6, y - 18), (x + max_w + 12, y + line_h * len(lines) + 4), (0, 0, 0), -1)
        for index, line in enumerate(lines):
            yy = y + index * line_h
            cv2.putText(image, line, (x, yy), font, scale, (0, 0, 0), thickness + 3, cv2.LINE_AA)
            cv2.putText(image, line, (x, yy), font, scale, (210, 255, 225), thickness, cv2.LINE_AA)

    def _fit_to_screen(self, image):
        if self.screen_width <= 0 or self.screen_height <= 0:
            return image
        height, width = image.shape[:2]
        scale = min(self.screen_width / width, self.screen_height / height)
        if scale <= 0 or abs(scale - 1.0) < 0.01:
            return image
        return cv2.resize(image, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA)

    def _handle_key(self, key: int) -> bool:
        if key in QUIT_KEYS:
            return True
        if self.review_state is not None:
            self._handle_review_key(key)
            return False
        if key in (ord("c"), ord("C")):
            self._capture()
        elif key in (ord("o"), ord("O")):
            self.live_overlay_enabled = not self.live_overlay_enabled
            self.status = f"overlay {'on' if self.live_overlay_enabled else 'off'}"
        elif key in (ord("i"), ord("I")):
            self.camera_settings.input_adjust = not self.camera_settings.input_adjust
            self._write_input_adjust()
            self.status = f"sync input {'on' if self.camera_settings.input_adjust else 'off'}"
        elif key == 9:
            self.adjust_index = (self.adjust_index + 1) % len(ADJUST_TARGETS)
            self.status = f"selected {ADJUST_TARGETS[self.adjust_index].name}"
        elif key in (ord("+"), ord("=")):
            self._nudge_selected(1)
        elif key in (ord("-"), ord("_")):
            self._nudge_selected(-1)
        elif key == ord("1"):
            self._apply_preset("pins")
        elif key == ord("2"):
            self._apply_preset("text")
        elif key == ord("3"):
            self._apply_preset("damage")
        elif key == ord("0"):
            self._apply_preset("reset")
        return False

    def _handle_review_key(self, key: int) -> None:
        if key in ENTER_KEYS:
            self._accept_roi()
        elif key in DELETE_KEYS or key in (ord("n"), ord("N")):
            self._mark_negative()
        elif key in (ord("a"), ord("A")):
            self._adjust_roi(-4, 0)
        elif key in (ord("d"), ord("D")):
            self._adjust_roi(4, 0)
        elif key in (ord("w"), ord("W")):
            self._adjust_roi(0, -4)
        elif key in (ord("s"), ord("S")):
            self._adjust_roi(0, 4)
        elif key in (ord("+"), ord("=")):
            self._scale_roi(0.005)
        elif key in (ord("-"), ord("_")):
            self._scale_roi(-0.005)

    def _capture(self) -> None:
        if self.last_frame is None or self.last_clean_bgr is None:
            self.status = "capture ignored: no frame"
            return
        frame = self.last_frame
        raw_bgr = self.last_clean_bgr.copy()
        capture_adjusted = self.camera_settings.input_adjust
        clean_bgr = raw_bgr if capture_adjusted else apply_adjustments(raw_bgr, self.image_settings)
        try:
            chip_box, method, score = self._initial_chip_box(frame, clean_bgr)
            record = self.storage.save_chip_roi_candidate(
                frame=frame,
                clean_bgr=clean_bgr,
                chip_box=chip_box,
                camera_settings=self.camera_settings,
                image_settings=self.image_settings,
                light_settings=self.light_settings,
                prefix=self.prefix,
                method=method,
                score=score,
                capture_adjusted=capture_adjusted,
            )
        except Exception as exc:  # noqa: BLE001
            self.status = f"capture failed: {exc}"
            return
        self.review_state = RoiReviewState(record=record, clean_bgr=clean_bgr, box=chip_box, capture_adjusted=capture_adjusted)
        self.status = f"captured {record.image_path.name} | {method} {score:.3f}"

    def _initial_chip_box(
        self,
        frame: CameraFrame,
        image_bgr,
    ) -> tuple[tuple[int, int, int, int] | None, str, float]:
        best = self._best_chip_detection(frame.detections, frame.width, frame.height)
        if best is not None:
            box, score = best
            return box, "board_chip_two_stage", score
        candidate = locate_chip_dark_edge(
            image_bgr,
            margin=0.35,
            min_side=220,
            square=True,
            max_area_ratio=0.35,
            center_bias=12.0,
        )
        if candidate is None:
            return None, "none", 0.0
        return candidate.box, candidate.method, candidate.score

    def _best_chip_detection(
        self,
        detections: list[Detection],
        width: int,
        height: int,
    ) -> tuple[tuple[int, int, int, int], float] | None:
        best_box: tuple[int, int, int, int] | None = None
        best_rank = -1.0
        best_conf = 0.0
        for detection in detections:
            if detection.class_id != 0:
                continue
            x1 = int(round(max(0.0, min(float(width - 1), detection.x1))))
            y1 = int(round(max(0.0, min(float(height - 1), detection.y1))))
            x2 = int(round(max(0.0, min(float(width - 1), detection.x2))))
            y2 = int(round(max(0.0, min(float(height - 1), detection.y2))))
            if x2 <= x1 or y2 <= y1:
                continue
            area = float((x2 - x1) * (y2 - y1))
            rank = max(0.001, float(detection.score)) * area
            if rank > best_rank:
                best_rank = rank
                best_conf = float(detection.score)
                best_box = clamp_box((x1, y1, x2, y2), width, height)
        if best_box is None:
            return None
        return best_box, max(0.0, best_conf)

    def _accept_roi(self) -> None:
        if self.review_state is None:
            return
        if self.review_state.box is None:
            self._mark_negative()
            return
        try:
            self.storage.update_chip_roi_label(
                self.review_state.record,
                self.review_state.clean_bgr,
                self.review_state.box,
                "accepted",
            )
        except Exception as exc:  # noqa: BLE001
            self.status = f"accept failed: {exc}"
            return
        name = self.review_state.record.image_path.name
        self.review_state = None
        self.status = f"accepted {name}"

    def _mark_negative(self) -> None:
        if self.review_state is None:
            return
        try:
            self.storage.update_chip_roi_label(
                self.review_state.record,
                self.review_state.clean_bgr,
                None,
                "negative",
            )
        except Exception as exc:  # noqa: BLE001
            self.status = f"negative failed: {exc}"
            return
        name = self.review_state.record.image_path.name
        self.review_state = None
        self.status = f"negative {name}"

    def _adjust_roi(self, dx: int, dy: int) -> None:
        if self.review_state is None or self.review_state.box is None:
            return
        x1, y1, x2, y2 = self.review_state.box
        self.review_state.box = clamp_box(
            (x1 + dx, y1 + dy, x2 + dx, y2 + dy),
            self.review_state.record.width,
            self.review_state.record.height,
        )
        self.status = "roi moved"

    def _scale_roi(self, margin: float) -> None:
        if self.review_state is None or self.review_state.box is None:
            return
        self.review_state.box = expand_box(
            self.review_state.box,
            self.review_state.record.width,
            self.review_state.record.height,
            margin,
            square=True,
        )
        self.status = "roi scaled"

    def _apply_preset(self, preset: str) -> None:
        if preset == "pins":
            self.image_settings = ImageAdjustSettings(brightness=-8, contrast=1.45, gamma=0.90, saturation=0.22, sharpness=1.25)
        elif preset == "text":
            self.image_settings = ImageAdjustSettings(brightness=-10, contrast=1.55, gamma=0.82, saturation=0.25, sharpness=1.05)
        elif preset == "damage":
            self.image_settings = ImageAdjustSettings(brightness=-6, contrast=1.30, gamma=0.95, saturation=0.30, sharpness=0.85)
        else:
            self.image_settings = ImageAdjustSettings()
            preset = "reset"
        self._sync_input_adjust_settings()
        self._write_input_adjust()
        self.status = f"preset {preset}"

    def _nudge_selected(self, direction: int) -> None:
        target = ADJUST_TARGETS[self.adjust_index]
        delta = target.step * direction
        if target.name == "brightness":
            self.image_settings.brightness = int(max(-80, min(80, self.image_settings.brightness + delta)))
        elif target.name == "contrast":
            self.image_settings.contrast = max(0.10, min(3.0, self.image_settings.contrast + delta))
        elif target.name == "gamma":
            self.image_settings.gamma = max(0.20, min(3.0, self.image_settings.gamma + delta))
        elif target.name == "saturation":
            self.image_settings.saturation = max(0.0, min(3.0, self.image_settings.saturation + delta))
        elif target.name == "sharpness":
            self.image_settings.sharpness = max(0.0, min(3.0, self.image_settings.sharpness + delta))
        elif target.name == "light":
            self.light_settings.brightness = max(0.0, min(self.light_settings.max_brightness, self.light_settings.brightness + delta))
            try:
                self.light_controller.set_brightness(self.light_settings.brightness)
            except Exception as exc:  # noqa: BLE001
                self.status = f"light failed: {exc}"
                return
        if target.name != "light":
            self._sync_input_adjust_settings()
            self._write_input_adjust()
        self.status = f"{target.name} adjusted"

    def _sync_input_adjust_settings(self) -> None:
        self.camera_settings.input_brightness = self.image_settings.brightness
        self.camera_settings.input_contrast = self.image_settings.contrast
        self.camera_settings.input_gamma = self.image_settings.gamma
        self.camera_settings.input_saturation = self.image_settings.saturation
        self.camera_settings.input_sharpness = self.image_settings.sharpness

    def _write_input_adjust(self) -> None:
        try:
            write_input_adjust_config(self.camera_settings)
        except Exception as exc:  # noqa: BLE001
            self.status = f"input adjust failed: {exc}"


def resolve_backend(value: str) -> str:
    if value != "auto":
        return value
    return "adb" if platform.system().lower().startswith("win") else "local"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenCV chip capture GUI for PC ADB or board-local display")
    parser.add_argument("--backend", choices=("auto", "adb", "local"), default="auto", help="Camera/control backend")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Capture output directory")
    parser.add_argument("--prefix", default="chip", help="Capture filename prefix")
    parser.add_argument("--window-name", default="Chip Capture CV", help="OpenCV window title")
    parser.add_argument("--screen-width", type=int, default=1024, help="Display fit width; 0 disables resize")
    parser.add_argument("--screen-height", type=int, default=600, help="Display fit height; 0 disables resize")
    parser.add_argument("--window-x", type=int, default=0, help="OpenCV window X position in normal window mode")
    parser.add_argument("--window-y", type=int, default=0, help="OpenCV window Y position in normal window mode")
    parser.add_argument("--fullscreen", action="store_true", help="Use OpenCV fullscreen window")
    parser.add_argument("--device", default="/dev/video73", help="Camera V4L2 device")
    parser.add_argument("--width", type=int, default=1280, help="Camera stream width")
    parser.add_argument("--height", type=int, default=720, help="Camera stream height")
    parser.add_argument("--fps", type=int, default=30, help="Camera FPS request")
    parser.add_argument("--conf", type=float, default=0.25, help="Chip model confidence")
    parser.add_argument("--chip-conf", type=float, default=0.25, help="Chip ROI confidence")
    parser.add_argument("--defect-conf", type=float, default=0.45, help="Defect confidence")
    parser.add_argument("--defect-model-kind", choices=("detect", "seg"), default="detect", help="Board defect postprocess kind")
    parser.add_argument("--remote-defect-model", help="Board defect RKNN model path for two-stage streams")
    parser.add_argument("--display-max-defects", type=int, default=20, help="Max defect boxes after display filtering")
    parser.add_argument("--light-brightness", type=float, default=0.50, help="WS2812 brightness")
    parser.add_argument("--light-rgb", default="190,255,100", help="WS2812 RGB")
    parser.add_argument("--no-input-adjust", dest="input_adjust", action="store_false", help="Disable board-side input adjustment")
    parser.set_defaults(input_adjust=True)
    return parser.parse_args(argv)


def make_settings(args: argparse.Namespace) -> tuple[CameraSettings, ImageAdjustSettings, LightSettings]:
    backend = resolve_backend(args.backend)
    camera_settings = CameraSettings(
        backend=backend,
        device=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        conf=args.conf,
        chip_conf=args.chip_conf,
        defect_conf=args.defect_conf,
        defect_model_kind=args.defect_model_kind,
        remote_defect_model=args.remote_defect_model
        or (CHIP_DEFECT_SEG_REMOTE_MODEL if args.defect_model_kind == "seg" else CHIP_REMOTE_MODEL),
        display_max_defects=args.display_max_defects,
        input_adjust=args.input_adjust,
    )
    image_settings = ImageAdjustSettings()
    channels = tuple(int(part.strip()) for part in args.light_rgb.split(",", 2))
    if len(channels) != 3:
        raise ValueError("--light-rgb must be R,G,B")
    light_settings = LightSettings(rgb=channels, brightness=args.light_brightness)
    return camera_settings, image_settings, light_settings


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    camera_settings, image_settings, light_settings = make_settings(args)
    app = OpenCvChipCaptureApp(
        camera_settings=camera_settings,
        image_settings=image_settings,
        light_settings=light_settings,
        output_dir=args.output_dir,
        prefix=args.prefix,
        window_name=args.window_name,
        screen_width=args.screen_width,
        screen_height=args.screen_height,
        window_x=args.window_x,
        window_y=args.window_y,
        fullscreen=args.fullscreen,
    )
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())

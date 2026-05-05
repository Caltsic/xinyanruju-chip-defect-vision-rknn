#!/usr/bin/env python3
"""Live-view RKNN detections streamed from TaishanPi IMX415 over ADB."""

from __future__ import annotations

import argparse
import math
import os
import shlex
import struct
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover - reported from main()
    cv2 = None
    np = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


MAGIC = b"RYL1"
HEADER_STRUCT = struct.Struct("<4sIIIII")
BOX_STRUCT = struct.Struct("<Ifffff")

YOLO11_REMOTE_WORKDIR = "/userdata/rknn_yolo11_demo"
YOLO11_REMOTE_BINARY = "./rknn_yolo11_camera_stream"
YOLO11_REMOTE_MODEL = "model/yolo11n_rk3576.rknn"
CHIP_REMOTE_WORKDIR = "/userdata/rknn_yolo11_demo"
CHIP_REMOTE_BINARY = "./rknn_chip_defect_camera_stream"
CHIP_REMOTE_MODEL = "model/chipcheck_yolov8_detect_split_int8.rknn"
CHIP_MAIXCAM_REMOTE_BINARY = "./rknn_chip_defect_maixcam_stream"
CHIP_ROI_REMOTE_BINARY = "./rknn_chip_roi_camera_stream"
CHIP_ROI_MAIXCAM_REMOTE_BINARY = "./rknn_chip_roi_maixcam_stream"
CHIP_TWO_STAGE_MAIXCAM_REMOTE_BINARY = "./rknn_chip_two_stage_maixcam_stream"
CHIP_ROI_INT8_REMOTE_MODEL = "model/chip_roi_yolov8_detect_split_int8.rknn"
CHIP_ROI_FP_REMOTE_MODEL = "model/chip_roi_yolov8_detect_fp.rknn"
CHIP_ROI_REMOTE_MODEL = CHIP_ROI_INT8_REMOTE_MODEL
REMOTE_DEVICE = "/dev/video42"
DEFAULT_REMOTE_LOG = "/tmp/rknn_yolo11_camera_stream.log"

DEFAULT_SERIAL = "2e2609c37dc21c0a"
DEFAULT_WIDTH = 960
DEFAULT_HEIGHT = 540
DEFAULT_FPS = 8
DEFAULT_SKIP = 8
DEFAULT_CONF = 0.25
DEFAULT_NMS = 0.45
DEFAULT_PROFILE = "chip-defect"

REMOTE_WS2812_SCRIPT = "/userdata/rknn_yolo11_demo/ws2812_spi.py"
DEFAULT_LIGHT_RGB = "190,255,100"
DEFAULT_LIGHT_BRIGHTNESS = 0.50
DEFAULT_LIGHT_COUNT = 8
DEFAULT_LIGHT_DEVICE = "/dev/spidev1.0"

DEFAULT_PREVIEW_BRIGHTNESS = -6
DEFAULT_PREVIEW_CONTRAST = 1.28
DEFAULT_PREVIEW_GAMMA = 0.91
DEFAULT_PREVIEW_SATURATION = 0.30
DEFAULT_PREVIEW_SHARPNESS = 0.85
DEFAULT_PREVIEW_DENOISE = 6
DEFAULT_INPUT_ADJUST_FILE = "/tmp/chip_input_adjust.conf"
DEFAULT_INPUT_BRIGHTNESS = DEFAULT_PREVIEW_BRIGHTNESS
DEFAULT_INPUT_CONTRAST = DEFAULT_PREVIEW_CONTRAST
DEFAULT_INPUT_GAMMA = DEFAULT_PREVIEW_GAMMA
DEFAULT_INPUT_SATURATION = DEFAULT_PREVIEW_SATURATION
DEFAULT_INPUT_SHARPNESS = DEFAULT_PREVIEW_SHARPNESS
DEFAULT_TWO_STAGE_DEFECT_CONF = 0.45
DEFAULT_TWO_STAGE_DISPLAY_MAX_DEFECTS = 20

MAX_DETECTIONS = 1024
MAX_PAYLOAD_BYTES = 256 * 1024 * 1024

COCO_CLASSES = [
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
]

CHIP_DEFECT_CLASSES = [
    "ZF-scratch",
    "scratch",
    "broken",
    "pinbreak",
]

CHIP_ROI_CLASSES = [
    "chip",
]

CHIP_TWO_STAGE_CLASSES = [
    "chip",
    *CHIP_DEFECT_CLASSES,
]

BOX_COLORS = [
    (56, 56, 255),
    (151, 157, 255),
    (31, 112, 255),
    (29, 178, 255),
    (49, 210, 207),
    (10, 249, 72),
    (23, 204, 146),
    (134, 219, 61),
    (52, 147, 26),
    (187, 212, 0),
    (168, 153, 44),
    (255, 194, 0),
    (147, 69, 52),
    (255, 115, 100),
    (236, 24, 0),
    (255, 56, 132),
    (133, 0, 82),
    (255, 56, 203),
    (200, 149, 255),
    (199, 55, 255),
]


class ProtocolError(RuntimeError):
    """Raised when the RYL1 binary stream is malformed."""


@dataclass(slots=True)
class Detection:
    class_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    score: float


@dataclass(slots=True)
class StreamFrame:
    width: int
    height: int
    frame_index: int
    detections: list[Detection]
    payload: bytes


@dataclass(slots=True)
class DetectionTrack:
    class_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    hits: int = 1
    missed: int = 0

    def as_detection(self) -> Detection:
        return Detection(self.class_id, self.x1, self.y1, self.x2, self.y2, self.score)


class FpsMeter:
    def __init__(self, window: int = 32) -> None:
        self.times: deque[float] = deque(maxlen=window)

    def tick(self) -> float:
        now = time.perf_counter()
        self.times.append(now)
        if len(self.times) < 2:
            return 0.0
        elapsed = self.times[-1] - self.times[0]
        return (len(self.times) - 1) / elapsed if elapsed > 0 else 0.0


def default_adb_path() -> str:
    candidates: list[Path] = []

    for env_name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        env_value = os.environ.get(env_name)
        if env_value:
            candidates.append(Path(env_value) / "platform-tools" / "adb.exe")

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Android" / "Sdk" / "platform-tools" / "adb.exe")

    candidates.extend(
        [
            Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
            Path("C:/Android/Sdk/platform-tools/adb.exe"),
            Path("C:/Android/platform-tools/adb.exe"),
            Path("C:/adb/adb.exe"),
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "adb"


def shell_join(parts: Iterable[object]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def adb_base_cmd(args: argparse.Namespace) -> list[str]:
    command = [args.adb]
    if args.serial:
        command.extend(["-s", args.serial])
    return command


def run_adb_shell(args: argparse.Namespace, script: str, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    command = adb_base_cmd(args)
    command.extend(["shell", script])
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def maybe_setup_ws2812(args: argparse.Namespace) -> None:
    if args.no_runtime_setup or args.profile == "yolo11":
        return
    remote_args = [
        "python3",
        REMOTE_WS2812_SCRIPT,
        "--device",
        args.light_device,
        "--count",
        args.light_count,
        "--brightness",
        args.light_brightness,
        "--rgb",
        args.light_rgb,
    ]
    script = " ".join(shlex.quote(str(part)) for part in remote_args)
    try:
        result = run_adb_shell(args, script, timeout=8.0)
    except Exception as exc:  # noqa: BLE001 - realtime view should still start
        print(f"Runtime setup warning: WS2812 setup failed: {exc}", file=sys.stderr)
        return

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        print(f"Runtime setup warning: WS2812 setup returned {result.returncode}{suffix}", file=sys.stderr)
        return
    print(
        f"Runtime setup: WS2812 rgb={args.light_rgb} brightness={args.light_brightness:.2f}",
        file=sys.stderr,
    )


def input_adjust_config_text(args: argparse.Namespace) -> str:
    enabled = 1 if getattr(args, "input_adjust", False) else 0
    return "\n".join(
        [
            f"enabled={enabled}",
            f"brightness={int(args.input_brightness)}",
            f"contrast={float(args.input_contrast):.6f}",
            f"gamma={float(args.input_gamma):.6f}",
            f"saturation={float(args.input_saturation):.6f}",
            f"sharpness={float(args.input_sharpness):.6f}",
            "",
        ]
    )


def write_remote_input_adjust(args: argparse.Namespace) -> None:
    path = getattr(args, "input_adjust_file", "")
    if not path or args.profile == "yolo11":
        return
    text = input_adjust_config_text(args)
    script = f"cat > {shlex.quote(path)} <<'EOF'\n{text}EOF"
    try:
        result = run_adb_shell(args, script, timeout=5.0)
    except Exception as exc:  # noqa: BLE001 - realtime view should still start from argv defaults
        print(f"Runtime setup warning: input adjust setup failed: {exc}", file=sys.stderr)
        return
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        print(f"Runtime setup warning: input adjust setup returned {result.returncode}{suffix}", file=sys.stderr)


def build_remote_command(args: argparse.Namespace) -> str:
    stream_parts = [
        args.remote_binary,
        "--model",
        args.remote_model,
        "--device",
        args.device,
        "--width",
        args.width,
        "--height",
        args.height,
        "--fps",
        args.fps,
        "--skip",
        args.skip,
        "--frames",
        args.frames,
        "--conf",
        args.conf,
        "--nms",
        args.nms,
    ]
    if args.camera_format:
        stream_parts.extend(["--format", args.camera_format])
    if args.roi:
        stream_parts.extend(["--roi", args.roi])
    if args.profile == "chip-two-stage-maixcam":
        stream_parts.extend(
            [
                "--two-stage",
                "--defect-model",
                CHIP_REMOTE_MODEL,
                "--chip-conf",
                args.chip_conf,
                "--defect-conf",
                args.defect_conf,
                "--roi-margin",
                args.roi_margin,
                "--roi-smooth-alpha",
                args.roi_smooth_alpha,
                "--roi-hold",
                args.roi_hold,
                "--chip-interval",
                args.chip_interval,
                "--defect-interval",
                args.defect_interval,
                "--defect-confirm",
                args.defect_confirm,
                "--defect-hold",
                args.defect_hold,
                "--defect-smooth-alpha",
                args.defect_smooth_alpha,
                "--defect-match-iou",
                args.defect_match_iou,
                "--defect-match-center",
                args.defect_match_center,
                "--defect-class-decay",
                args.defect_class_decay,
            ]
        )
    if getattr(args, "input_adjust", False):
        stream_parts.extend(
            [
                "--input-adjust",
                "--input-brightness",
                args.input_brightness,
                "--input-contrast",
                args.input_contrast,
                "--input-gamma",
                args.input_gamma,
                "--input-saturation",
                args.input_saturation,
                "--input-sharpness",
                args.input_sharpness,
            ]
        )
    else:
        stream_parts.append("--no-input-adjust")
    if getattr(args, "input_adjust_file", ""):
        stream_parts.extend(["--input-adjust-file", args.input_adjust_file])
    stream_command = shell_join(stream_parts)
    return (
        f"cd {shlex.quote(args.remote_workdir)} && "
        "export LD_LIBRARY_PATH=$PWD/lib:$LD_LIBRARY_PATH && "
        f"exec {stream_command} 2>{shlex.quote(args.remote_log)}"
    )


def start_adb_stream(args: argparse.Namespace) -> subprocess.Popen[bytes]:
    command = adb_base_cmd(args)
    command.extend(["exec-out", "sh", "-c", build_remote_command(args)])
    return subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )


def cleanup_remote_stream(args: argparse.Namespace) -> None:
    command = adb_base_cmd(args)
    binary_name = PurePosixPath(args.remote_binary).name
    cleanup = f"pkill -f {shlex.quote(binary_name)} 2>/dev/null || true"
    command.extend(["shell", cleanup])
    try:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
    except Exception:
        pass


def stop_adb_process(process: subprocess.Popen[bytes] | None) -> str:
    if process is None:
        return ""

    if process.stdout is not None:
        try:
            process.stdout.close()
        except Exception:
            pass

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    stderr_text = ""
    if process.stderr is not None:
        try:
            stderr_text = process.stderr.read().decode("utf-8", errors="replace").strip()
        except Exception:
            stderr_text = ""
        try:
            process.stderr.close()
        except Exception:
            pass
    return stderr_text


def read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def read_stream_frame(stream: BinaryIO, remote_log: str) -> StreamFrame | None:
    header = read_exact(stream, HEADER_STRUCT.size)
    if not header:
        return None
    if len(header) != HEADER_STRUCT.size:
        raise ProtocolError(f"short header: expected {HEADER_STRUCT.size} bytes, got {len(header)}")

    magic, width, height, frame_index, det_count, payload_size = HEADER_STRUCT.unpack(header)
    if magic != MAGIC:
        preview = header[: min(len(header), 16)].hex(" ")
        raise ProtocolError(
            f"bad magic: expected {MAGIC!r}, got {magic!r}. "
            f"stdout may be polluted by logs; check board log {remote_log}. "
            f"header preview: {preview}"
        )

    if width <= 0 or height <= 0 or width % 2 != 0 or height % 2 != 0:
        raise ProtocolError(f"invalid NV12 frame size from stream: {width}x{height}")
    if det_count > MAX_DETECTIONS:
        raise ProtocolError(f"invalid detection count: {det_count} > {MAX_DETECTIONS}")
    if payload_size > MAX_PAYLOAD_BYTES:
        raise ProtocolError(f"payload too large: {payload_size} bytes")

    expected_payload_size = width * height * 3 // 2
    if payload_size != expected_payload_size:
        raise ProtocolError(
            f"payload size mismatch for {width}x{height} NV12: "
            f"expected {expected_payload_size}, got {payload_size}"
        )

    box_bytes_size = det_count * BOX_STRUCT.size
    box_bytes = read_exact(stream, box_bytes_size)
    if len(box_bytes) != box_bytes_size:
        raise ProtocolError(f"short detection block: expected {box_bytes_size} bytes, got {len(box_bytes)}")

    detections: list[Detection] = []
    for offset in range(0, box_bytes_size, BOX_STRUCT.size):
        class_id, score, x1, y1, x2, y2 = BOX_STRUCT.unpack_from(box_bytes, offset)
        detections.append(Detection(class_id, x1, y1, x2, y2, score))

    payload = read_exact(stream, payload_size)
    if len(payload) != payload_size:
        raise ProtocolError(f"short NV12 payload: expected {payload_size} bytes, got {len(payload)}")

    return StreamFrame(width, height, frame_index, detections, payload)


def nv12_to_bgr(payload: bytes, width: int, height: int) -> np.ndarray:
    expected = width * height * 3 // 2
    if len(payload) != expected:
        raise ValueError(f"expected {expected} NV12 bytes, got {len(payload)}")
    yuv = np.frombuffer(payload, dtype=np.uint8).reshape((height * 3 // 2, width))
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)


def apply_preview_adjustments(image: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    if args.no_preview_adjust:
        return image.copy()

    result = image.copy()
    denoise = max(0, min(30, int(args.preview_denoise)))
    if denoise > 0:
        if denoise <= 8:
            result = cv2.bilateralFilter(result, 5, 8 + denoise * 3, 5)
        elif denoise <= 18:
            result = cv2.bilateralFilter(result, 7, 12 + denoise * 2, 7)
        else:
            result = cv2.bilateralFilter(result, 9, 18 + denoise * 2, 9)

    contrast = max(0.0, float(args.preview_contrast))
    brightness = int(args.preview_brightness)
    if not math.isclose(contrast, 1.0, rel_tol=1e-3, abs_tol=1e-3) or brightness != 0:
        result = cv2.convertScaleAbs(result, alpha=contrast, beta=brightness)

    gamma = max(0.05, min(5.0, float(args.preview_gamma)))
    if not math.isclose(gamma, 1.0, rel_tol=1e-3, abs_tol=1e-3):
        inv_gamma = 1.0 / gamma
        lut = np.array([((value / 255.0) ** inv_gamma) * 255.0 for value in range(256)], dtype=np.uint8)
        result = cv2.LUT(result, lut)

    saturation = max(0.0, float(args.preview_saturation))
    if not math.isclose(saturation, 1.0, rel_tol=1e-3, abs_tol=1e-3):
        hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0, 255)
        result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    sharpness = max(0.0, float(args.preview_sharpness))
    if sharpness > 0:
        blur = cv2.GaussianBlur(result, (0, 0), sigmaX=1.2)
        result = cv2.addWeighted(result, 1.0 + sharpness, blur, -sharpness, 0)

    return result


def normalized_box(detection: Detection, width: int, height: int) -> Detection | None:
    values = (detection.x1, detection.y1, detection.x2, detection.y2, detection.score)
    if not all(math.isfinite(value) for value in values):
        return None

    x1, y1, x2, y2 = detection.x1, detection.y1, detection.x2, detection.y2
    max_coord = max(abs(x1), abs(y1), abs(x2), abs(y2))
    if max_coord <= 1.5:
        x1 *= width
        x2 *= width
        y1 *= height
        y2 *= height

    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1

    x1 = max(0.0, min(float(width - 1), x1))
    y1 = max(0.0, min(float(height - 1), y1))
    x2 = max(0.0, min(float(width - 1), x2))
    y2 = max(0.0, min(float(height - 1), y2))

    if x2 <= x1 or y2 <= y1:
        return None
    return Detection(detection.class_id, x1, y1, x2, y2, detection.score)


def box_iou(a: Detection, b: Detection) -> float:
    left = max(a.x1, b.x1)
    top = max(a.y1, b.y1)
    right = min(a.x2, b.x2)
    bottom = min(a.y2, b.y2)
    inter_w = max(0.0, right - left)
    inter_h = max(0.0, bottom - top)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a.x2 - a.x1) * max(0.0, a.y2 - a.y1)
    area_b = max(0.0, b.x2 - b.x1) * max(0.0, b.y2 - b.y1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def center_distance_ratio(a: Detection, b: Detection) -> float:
    ax = (a.x1 + a.x2) * 0.5
    ay = (a.y1 + a.y2) * 0.5
    bx = (b.x1 + b.x2) * 0.5
    by = (b.y1 + b.y2) * 0.5
    distance = math.hypot(ax - bx, ay - by)
    scale = max(
        1.0,
        a.x2 - a.x1,
        a.y2 - a.y1,
        b.x2 - b.x1,
        b.y2 - b.y1,
    )
    return distance / scale


class DetectionSmoother:
    def __init__(
        self,
        alpha: float = 0.35,
        hold_frames: int = 5,
        iou_threshold: float = 0.12,
        center_threshold: float = 0.45,
        min_hits: int = 1,
    ) -> None:
        self.alpha = max(0.01, min(1.0, float(alpha)))
        self.hold_frames = max(0, int(hold_frames))
        self.iou_threshold = max(0.0, min(1.0, float(iou_threshold)))
        self.center_threshold = max(0.0, float(center_threshold))
        self.min_hits = max(1, int(min_hits))
        self.tracks: list[DetectionTrack] = []

    @staticmethod
    def _track_detection(track: DetectionTrack) -> Detection:
        return Detection(track.class_id, track.x1, track.y1, track.x2, track.y2, track.score)

    def _match_score(self, track: DetectionTrack, detection: Detection) -> float | None:
        if track.class_id != detection.class_id:
            return None
        track_det = self._track_detection(track)
        iou = box_iou(track_det, detection)
        center_ratio = center_distance_ratio(track_det, detection)
        if iou < self.iou_threshold and center_ratio > self.center_threshold:
            return None
        center_bonus = 0.0
        if self.center_threshold > 0:
            center_bonus = max(0.0, 1.0 - center_ratio / self.center_threshold)
        return iou + 0.25 * center_bonus

    def update(self, detections: Iterable[Detection], width: int, height: int) -> list[Detection]:
        normalized = [
            detection
            for detection in (normalized_box(raw, width, height) for raw in detections)
            if detection is not None
        ]
        normalized.sort(key=lambda item: item.score, reverse=True)

        unmatched_tracks = set(range(len(self.tracks)))
        updated_tracks: set[int] = set()

        for detection in normalized:
            best_index: int | None = None
            best_score = -1.0
            for track_index in unmatched_tracks:
                score = self._match_score(self.tracks[track_index], detection)
                if score is not None and score > best_score:
                    best_score = score
                    best_index = track_index

            if best_index is None:
                self.tracks.append(
                    DetectionTrack(
                        detection.class_id,
                        detection.x1,
                        detection.y1,
                        detection.x2,
                        detection.y2,
                        detection.score,
                    )
                )
                updated_tracks.add(len(self.tracks) - 1)
                continue

            track = self.tracks[best_index]
            a = self.alpha
            track.x1 = track.x1 * (1.0 - a) + detection.x1 * a
            track.y1 = track.y1 * (1.0 - a) + detection.y1 * a
            track.x2 = track.x2 * (1.0 - a) + detection.x2 * a
            track.y2 = track.y2 * (1.0 - a) + detection.y2 * a
            track.score = track.score * (1.0 - a) + detection.score * a
            track.hits += 1
            track.missed = 0
            unmatched_tracks.remove(best_index)
            updated_tracks.add(best_index)

        next_tracks: list[DetectionTrack] = []
        for index, track in enumerate(self.tracks):
            if index not in updated_tracks:
                track.missed += 1
                track.score *= 0.90
            if track.missed <= self.hold_frames:
                next_tracks.append(track)
        self.tracks = next_tracks

        visible = [
            track.as_detection()
            for track in self.tracks
            if (track.class_id == 0 or track.hits >= self.min_hits) and track.score > 0.001
        ]
        visible.sort(key=lambda item: (item.class_id, -item.score))
        return visible


def class_agnostic_nms(detections: list[Detection], threshold: float, max_count: int) -> list[Detection]:
    threshold = max(0.0, min(1.0, float(threshold)))
    sorted_detections = sorted(detections, key=lambda item: item.score, reverse=True)
    limit = len(sorted_detections) if max_count <= 0 else max_count
    kept: list[Detection] = []
    for detection in sorted_detections:
        if all(box_iou(detection, kept_detection) < threshold for kept_detection in kept):
            kept.append(detection)
            if len(kept) >= limit:
                break
    return kept


def filter_display_detections(
    detections: list[Detection],
    width: int,
    height: int,
    args: argparse.Namespace,
) -> list[Detection]:
    if args.profile != "chip-two-stage-maixcam" or args.no_display_filter:
        return detections

    normalized = [
        detection
        for detection in (normalized_box(raw, width, height) for raw in detections)
        if detection is not None
    ]
    chips = [detection for detection in normalized if detection.class_id == 0]
    defects = [detection for detection in normalized if detection.class_id != 0]

    selected: list[Detection] = []
    if chips:
        selected.append(max(chips, key=lambda item: item.score))
    selected.extend(class_agnostic_nms(defects, args.display_nms, args.display_max_defects))
    return selected


def class_name(class_id: int, class_names: list[str]) -> str:
    if 0 <= class_id < len(class_names):
        return class_names[class_id]
    return str(class_id)


def class_color(class_id: int) -> tuple[int, int, int]:
    return BOX_COLORS[class_id % len(BOX_COLORS)]


def put_label(
    image: np.ndarray,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
    font_scale: float = 0.55,
) -> None:
    text_size, baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 2)
    text_w, text_h = text_size
    _, image_w = image.shape[:2]

    x = max(0, min(x, max(0, image_w - text_w - 8)))
    y = max(text_h + baseline + 4, y)

    top_left = (x, y - text_h - baseline - 4)
    bottom_right = (x + text_w + 6, y + baseline)
    cv2.rectangle(image, top_left, bottom_right, color, -1)
    cv2.putText(
        image,
        text,
        (x + 3, y - 4),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )


def draw_detections(image: np.ndarray, detections: list[Detection], class_names: list[str]) -> int:
    height, width = image.shape[:2]
    drawn = 0
    for raw_detection in detections:
        detection = normalized_box(raw_detection, width, height)
        if detection is None:
            continue

        color = class_color(detection.class_id)
        x1 = int(round(detection.x1))
        y1 = int(round(detection.y1))
        x2 = int(round(detection.x2))
        y2 = int(round(detection.y2))
        score = detection.score
        score_text = f"{score:.2f}" if score <= 1.0 else f"{score:.1f}"
        label = f"{class_name(detection.class_id, class_names)} {score_text}"

        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        put_label(image, label, x1, y1, color)
        drawn += 1
    return drawn


def focus_score(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def draw_status(image: np.ndarray, fps: float, frame_info: StreamFrame, raw_count: int, drawn_count: int, focus: float) -> None:
    text = (
        f"FPS {fps:.1f} | focus {focus:.0f} | "
        f"{frame_info.width}x{frame_info.height} | det {raw_count}/{drawn_count} | frame {frame_info.frame_index}"
    )
    text_size, baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
    text_w, text_h = text_size
    cv2.rectangle(image, (8, 8), (text_w + 24, text_h + baseline + 20), (0, 0, 0), -1)
    cv2.putText(
        image,
        text,
        (16, text_h + 14),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def save_snapshot(path: Path, frame: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"failed to write snapshot: {path}")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def threshold_float(value: str) -> float:
    parsed = float(value)
    if not 0.0 < parsed < 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed


def profile_defaults(profile: str) -> tuple[str, str, str, list[str], str]:
    if profile == "yolo11":
        return (
            YOLO11_REMOTE_WORKDIR,
            YOLO11_REMOTE_BINARY,
            YOLO11_REMOTE_MODEL,
            COCO_CLASSES,
            "RKNN YOLO11 IMX415 Live",
        )
    if profile == "chip-defect-maixcam":
        return (
            CHIP_REMOTE_WORKDIR,
            CHIP_MAIXCAM_REMOTE_BINARY,
            CHIP_REMOTE_MODEL,
            CHIP_DEFECT_CLASSES,
            "RKNN Chip Defect MaixCAM Live",
        )
    if profile == "chip-roi":
        return (
            CHIP_REMOTE_WORKDIR,
            CHIP_ROI_REMOTE_BINARY,
            CHIP_ROI_REMOTE_MODEL,
            CHIP_ROI_CLASSES,
            "RKNN Chip ROI IMX415 Live",
        )
    if profile == "chip-roi-maixcam":
        return (
            CHIP_REMOTE_WORKDIR,
            CHIP_ROI_MAIXCAM_REMOTE_BINARY,
            CHIP_ROI_REMOTE_MODEL,
            CHIP_ROI_CLASSES,
            "RKNN Chip ROI MaixCAM Live",
        )
    if profile == "chip-two-stage-maixcam":
        return (
            CHIP_REMOTE_WORKDIR,
            CHIP_TWO_STAGE_MAIXCAM_REMOTE_BINARY,
            CHIP_ROI_REMOTE_MODEL,
            CHIP_TWO_STAGE_CLASSES,
            "RKNN Chip Two-Stage MaixCAM Live",
        )
    return (
        CHIP_REMOTE_WORKDIR,
        CHIP_REMOTE_BINARY,
        CHIP_REMOTE_MODEL,
        CHIP_DEFECT_CLASSES,
        "RKNN Chip Defect IMX415 Live",
    )


def load_class_names(args: argparse.Namespace) -> list[str]:
    if args.labels:
        labels = [
            line.strip()
            for line in args.labels.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if labels:
            return labels

    return list(args.default_class_names)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=default_adb_path(), help="Path to adb.exe")
    parser.add_argument("--serial", default=DEFAULT_SERIAL, help="ADB serial; pass an empty string to omit -s")
    parser.add_argument(
        "--profile",
        choices=("chip-defect", "chip-defect-maixcam", "chip-roi", "chip-roi-maixcam", "chip-two-stage-maixcam", "yolo11"),
        default=DEFAULT_PROFILE,
        help="Remote binary/model/label preset",
    )
    parser.add_argument("--remote-workdir", help="Board working directory")
    parser.add_argument("--remote-binary", help="Board stream binary path relative to remote workdir")
    parser.add_argument("--remote-model", help="Board RKNN model path relative to remote workdir")
    parser.add_argument("--labels", type=Path, help="Local label file for drawing class names")
    parser.add_argument("--width", type=positive_int, default=DEFAULT_WIDTH, help="Board camera stream width")
    parser.add_argument("--height", type=positive_int, default=DEFAULT_HEIGHT, help="Board camera stream height")
    parser.add_argument("--device", default=REMOTE_DEVICE, help="Board V4L2 output node, e.g. /dev/video42 for CSI1 or /dev/video51 for CSI3")
    parser.add_argument("--camera-format", choices=("yuyv", "mjpg"), help="Board V4L2 pixel format for single-plane UVC devices")
    parser.add_argument("--roi", help="Board-side inference crop as X,Y,W,H; display frame remains full size")
    parser.add_argument("--fps", type=positive_int, default=DEFAULT_FPS, help="Board stream FPS request")
    parser.add_argument("--frames", type=nonnegative_int, default=0, help="Frame count; 0 means run until stopped")
    parser.add_argument("--skip", type=nonnegative_int, default=DEFAULT_SKIP, help="Initial frames skipped by board")
    parser.add_argument("--conf", type=threshold_float, default=DEFAULT_CONF, help="Board detection confidence threshold")
    parser.add_argument("--chip-conf", type=threshold_float, default=0.25, help="Board chip ROI confidence threshold for two-stage streams")
    parser.add_argument("--defect-conf", type=threshold_float, help="Board defect confidence threshold for two-stage streams; defaults to --conf")
    parser.add_argument("--roi-margin", type=threshold_float, default=0.08, help="Chip ROI expansion ratio for two-stage streams")
    parser.add_argument("--roi-smooth-alpha", type=threshold_float, default=0.35, help="Board-side chip ROI EMA alpha for two-stage streams")
    parser.add_argument("--roi-hold", type=nonnegative_int, default=3, help="Board-side frames to hold the last chip ROI if one frame misses")
    parser.add_argument("--chip-interval", type=positive_int, default=3, help="Board-side chip ROI inference interval for two-stage streams")
    parser.add_argument("--defect-interval", type=positive_int, default=2, help="Board-side defect inference interval for two-stage streams")
    parser.add_argument("--defect-confirm", type=positive_int, default=3, help="Board-side matched defect updates required before output")
    parser.add_argument("--defect-hold", type=nonnegative_int, default=3, help="Board-side defect updates to hold after a miss")
    parser.add_argument("--defect-smooth-alpha", type=threshold_float, default=0.35, help="Board-side defect box EMA alpha")
    parser.add_argument("--defect-match-iou", type=threshold_float, default=0.10, help="Board-side defect track IoU match gate")
    parser.add_argument("--defect-match-center", type=threshold_float, default=0.55, help="Board-side defect track center-distance gate in box-size units")
    parser.add_argument("--defect-class-decay", type=threshold_float, default=0.85, help="Board-side defect class vote decay")
    parser.add_argument("--nms", type=threshold_float, default=DEFAULT_NMS, help="Board NMS IoU threshold")
    parser.add_argument("--smooth-boxes", dest="smooth_boxes", action="store_true", help="Smooth displayed boxes with a short temporal tracker")
    parser.add_argument("--no-smooth-boxes", dest="smooth_boxes", action="store_false", help="Draw raw per-frame detection boxes")
    parser.set_defaults(smooth_boxes=None)
    parser.add_argument("--smooth-alpha", type=threshold_float, default=0.35, help="PC-side display smoothing alpha")
    parser.add_argument("--smooth-hold", type=nonnegative_int, default=2, help="PC-side frames to keep unmatched displayed boxes")
    parser.add_argument("--smooth-iou", type=float, default=0.12, help="PC-side IoU match threshold for display smoothing")
    parser.add_argument("--smooth-center", type=float, default=0.45, help="PC-side center-distance match threshold in box-size units")
    parser.add_argument("--smooth-min-hits", type=positive_int, default=2, help="PC-side track hits before a smoothed defect box is drawn")
    parser.add_argument(
        "--display-max-defects",
        type=nonnegative_int,
        default=DEFAULT_TWO_STAGE_DISPLAY_MAX_DEFECTS,
        help="Max defect boxes drawn in chip-two-stage display after display NMS; 0 means no cap",
    )
    parser.add_argument("--display-nms", type=float, default=0.30, help="Class-agnostic display NMS IoU for chip-two-stage view")
    parser.add_argument("--no-display-filter", action="store_true", help="Do not cap/NMS boxes for chip-two-stage display")
    parser.add_argument("--headless", action="store_true", help="Do not open an OpenCV window")
    parser.add_argument("--save-snapshot", type=Path, help="Save the last annotated frame")
    parser.add_argument("--save-clean-snapshot", type=Path, help="Save the last decoded camera frame before overlays")
    parser.add_argument("--window-name", help="OpenCV window title")
    parser.add_argument("--remote-log", default=DEFAULT_REMOTE_LOG, help="Board-side stderr log path")
    parser.add_argument("--no-runtime-setup", action="store_true", help="Do not set WS2812 defaults before chip realtime streams")
    parser.add_argument("--light-rgb", default=DEFAULT_LIGHT_RGB, help="WS2812 RGB set before chip realtime streams")
    parser.add_argument("--light-brightness", type=float, default=DEFAULT_LIGHT_BRIGHTNESS, help="WS2812 brightness set before chip realtime streams")
    parser.add_argument("--light-count", type=positive_int, default=DEFAULT_LIGHT_COUNT, help="WS2812 LED count")
    parser.add_argument("--light-device", default=DEFAULT_LIGHT_DEVICE, help="Board spidev node for WS2812")
    parser.add_argument("--input-adjust", dest="input_adjust", action="store_true", help="Apply board-side RGB adjustments before NPU and display stream")
    parser.add_argument("--no-input-adjust", dest="input_adjust", action="store_false", help="Do not apply board-side RGB adjustments before NPU")
    parser.set_defaults(input_adjust=None)
    parser.add_argument("--input-brightness", type=int, default=DEFAULT_INPUT_BRIGHTNESS, help="Board-side RGB brightness beta before NPU")
    parser.add_argument("--input-contrast", type=float, default=DEFAULT_INPUT_CONTRAST, help="Board-side RGB contrast alpha before NPU")
    parser.add_argument("--input-gamma", type=float, default=DEFAULT_INPUT_GAMMA, help="Board-side RGB gamma before NPU")
    parser.add_argument("--input-saturation", type=float, default=DEFAULT_INPUT_SATURATION, help="Board-side RGB saturation multiplier before NPU")
    parser.add_argument("--input-sharpness", type=float, default=DEFAULT_INPUT_SHARPNESS, help="Board-side lightweight unsharp amount before NPU")
    parser.add_argument("--input-adjust-file", default=DEFAULT_INPUT_ADJUST_FILE, help="Board-side live input-adjust control file")
    parser.add_argument("--no-preview-adjust", action="store_true", help="Do not apply PC-side preview image adjustments")
    parser.add_argument("--preview-brightness", type=int, default=DEFAULT_PREVIEW_BRIGHTNESS, help="PC preview brightness beta")
    parser.add_argument("--preview-contrast", type=float, default=DEFAULT_PREVIEW_CONTRAST, help="PC preview contrast alpha")
    parser.add_argument("--preview-gamma", type=float, default=DEFAULT_PREVIEW_GAMMA, help="PC preview gamma")
    parser.add_argument("--preview-saturation", type=float, default=DEFAULT_PREVIEW_SATURATION, help="PC preview saturation multiplier")
    parser.add_argument("--preview-sharpness", type=float, default=DEFAULT_PREVIEW_SHARPNESS, help="PC preview unsharp amount")
    parser.add_argument("--preview-denoise", type=int, default=DEFAULT_PREVIEW_DENOISE, help="PC preview lightweight denoise strength")
    args = parser.parse_args()

    default_workdir, default_binary, default_model, default_labels, default_window = profile_defaults(args.profile)
    args.remote_workdir = args.remote_workdir or default_workdir
    args.remote_binary = args.remote_binary or default_binary
    args.remote_model = args.remote_model or default_model
    args.default_class_names = default_labels
    args.window_name = args.window_name or default_window
    if args.smooth_boxes is None:
        args.smooth_boxes = args.profile == "chip-two-stage-maixcam"
    if args.defect_conf is None:
        args.defect_conf = DEFAULT_TWO_STAGE_DEFECT_CONF if args.profile == "chip-two-stage-maixcam" else args.conf
    if args.input_adjust is None:
        args.input_adjust = args.profile == "chip-two-stage-maixcam"
    args.input_contrast = max(0.0, min(float(args.input_contrast), 5.0))
    args.input_gamma = max(0.05, min(float(args.input_gamma), 5.0))
    args.input_saturation = max(0.0, min(float(args.input_saturation), 5.0))
    args.input_sharpness = max(0.0, min(float(args.input_sharpness), 3.0))

    if args.profile in ("chip-defect-maixcam", "chip-roi-maixcam", "chip-two-stage-maixcam"):
        if args.device == REMOTE_DEVICE:
            args.device = "/dev/video73"
        if args.width == DEFAULT_WIDTH:
            args.width = 1280
        if args.height == DEFAULT_HEIGHT:
            args.height = 720
        if args.fps == DEFAULT_FPS:
            args.fps = 30
        if args.skip == DEFAULT_SKIP:
            args.skip = 3
        if args.camera_format is None:
            args.camera_format = "mjpg"

    if args.width % 2 != 0 or args.height % 2 != 0:
        parser.error("NV12 width and height must be even")
    if not 0.0 <= args.light_brightness <= 1.0:
        parser.error("--light-brightness must be between 0.0 and 1.0")
    return args


def print_headless_status(
    frame_info: StreamFrame,
    fps: float,
    raw_count: int,
    drawn_count: int,
    focus: float,
    last_print: float,
) -> float:
    now = time.perf_counter()
    if now - last_print < 1.0:
        return last_print
    print(
        f"frame={frame_info.frame_index} fps={fps:.1f} "
        f"focus={focus:.0f} size={frame_info.width}x{frame_info.height} det={raw_count}/{drawn_count}",
        file=sys.stderr,
    )
    return now


def main() -> int:
    if IMPORT_ERROR is not None:
        print(f"Missing dependency: {IMPORT_ERROR}", file=sys.stderr)
        print("Install opencv-python and numpy in the Python environment used to run this script.", file=sys.stderr)
        return 2

    args = parse_args()
    class_names = load_class_names(args)
    process: subprocess.Popen[bytes] | None = None
    process_started = False
    last_frame: np.ndarray | None = None
    last_clean_frame: np.ndarray | None = None
    frames_seen = 0
    exit_code = 0
    fps_meter = FpsMeter()
    last_headless_print = 0.0
    smoother = (
        DetectionSmoother(
            alpha=args.smooth_alpha,
            hold_frames=args.smooth_hold,
            iou_threshold=args.smooth_iou,
            center_threshold=args.smooth_center,
            min_hits=args.smooth_min_hits,
        )
        if args.smooth_boxes
        else None
    )

    try:
        maybe_setup_ws2812(args)
        write_remote_input_adjust(args)
        process = start_adb_stream(args)
        process_started = True
        assert process.stdout is not None

        if not args.headless:
            cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)

        while True:
            frame_info = read_stream_frame(process.stdout, args.remote_log)
            if frame_info is None:
                break

            clean_frame = nv12_to_bgr(frame_info.payload, frame_info.width, frame_info.height)
            last_clean_frame = clean_frame.copy()
            fps = fps_meter.tick()
            focus = focus_score(clean_frame)
            raw_count = len(frame_info.detections)
            frame = clean_frame.copy() if args.input_adjust else apply_preview_adjustments(clean_frame, args)
            display_detections = (
                smoother.update(frame_info.detections, frame_info.width, frame_info.height)
                if smoother is not None
                else frame_info.detections
            )
            display_detections = filter_display_detections(
                display_detections,
                frame_info.width,
                frame_info.height,
                args,
            )
            drawn_count = draw_detections(frame, display_detections, class_names)
            draw_status(frame, fps, frame_info, raw_count, drawn_count, focus)
            last_frame = frame
            frames_seen += 1

            if args.headless:
                last_headless_print = print_headless_status(
                    frame_info,
                    fps,
                    raw_count,
                    drawn_count,
                    focus,
                    last_headless_print,
                )
            else:
                cv2.imshow(args.window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q"), ord("Q")):
                    break

            if args.frames > 0 and frames_seen >= args.frames:
                break

    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
    except FileNotFoundError as exc:
        print(f"Failed to start adb: {exc}", file=sys.stderr)
        exit_code = 2
    except ProtocolError as exc:
        print(f"Protocol error: {exc}", file=sys.stderr)
        print(f"If board-side logs reached stdout, inspect: adb shell cat {args.remote_log}", file=sys.stderr)
        exit_code = 2
    except Exception as exc:  # noqa: BLE001 - top-level diagnostic for a CLI tool
        print(f"Live view failed: {exc}", file=sys.stderr)
        exit_code = 2
    finally:
        adb_stderr = stop_adb_process(process)
        if process_started:
            cleanup_remote_stream(args)
        if not args.headless and cv2 is not None:
            cv2.destroyAllWindows()
        print(f"Processed frames: {frames_seen}", file=sys.stderr)
        if args.save_snapshot and last_frame is not None:
            try:
                save_snapshot(args.save_snapshot, last_frame)
                print(f"Saved snapshot: {args.save_snapshot}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 - report cleanup-time failure
                print(f"Snapshot save failed: {exc}", file=sys.stderr)
                exit_code = 2
        if args.save_clean_snapshot and last_clean_frame is not None:
            try:
                save_snapshot(args.save_clean_snapshot, last_clean_frame)
                print(f"Saved clean snapshot: {args.save_clean_snapshot}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 - report cleanup-time failure
                print(f"Clean snapshot save failed: {exc}", file=sys.stderr)
                exit_code = 2
        if adb_stderr and (exit_code != 0 or frames_seen == 0):
            print(f"ADB stderr: {adb_stderr}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

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
CHIP_REMOTE_MODEL = "model/chipcheck_yolov8_detect_int8.rknn"
CHIP_MAIXCAM_REMOTE_BINARY = "./rknn_chip_defect_maixcam_stream"
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
        choices=("chip-defect", "chip-defect-maixcam", "yolo11"),
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
    parser.add_argument("--nms", type=threshold_float, default=DEFAULT_NMS, help="Board NMS IoU threshold")
    parser.add_argument("--headless", action="store_true", help="Do not open an OpenCV window")
    parser.add_argument("--save-snapshot", type=Path, help="Save the last annotated frame")
    parser.add_argument("--save-clean-snapshot", type=Path, help="Save the last decoded camera frame before overlays")
    parser.add_argument("--window-name", help="OpenCV window title")
    parser.add_argument("--remote-log", default=DEFAULT_REMOTE_LOG, help="Board-side stderr log path")
    args = parser.parse_args()

    default_workdir, default_binary, default_model, default_labels, default_window = profile_defaults(args.profile)
    args.remote_workdir = args.remote_workdir or default_workdir
    args.remote_binary = args.remote_binary or default_binary
    args.remote_model = args.remote_model or default_model
    args.default_class_names = default_labels
    args.window_name = args.window_name or default_window
    if args.profile == "chip-defect-maixcam":
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

    try:
        process = start_adb_stream(args)
        process_started = True
        assert process.stdout is not None

        if not args.headless:
            cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)

        while True:
            frame_info = read_stream_frame(process.stdout, args.remote_log)
            if frame_info is None:
                break

            frame = nv12_to_bgr(frame_info.payload, frame_info.width, frame_info.height)
            last_clean_frame = frame.copy()
            fps = fps_meter.tick()
            focus = focus_score(frame)
            raw_count = len(frame_info.detections)
            drawn_count = draw_detections(frame, frame_info.detections, class_names)
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

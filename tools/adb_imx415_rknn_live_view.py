#!/usr/bin/env python3
"""Live-view RKNN YOLO11 IMX415 detections streamed from TaishanPi over ADB."""

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
from pathlib import Path
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


DETECT_MODE = "detect"
POSE_MODE = "pose"

DETECT_MAGIC = b"RYL1"
POSE_MAGIC = b"RYP1"
DETECT_HEADER_STRUCT = struct.Struct("<4sIIIII")
POSE_HEADER_STRUCT = struct.Struct("<4sIIIIIIII")
BOX_STRUCT = struct.Struct("<Ifffff")
KEYPOINT_STRUCT = struct.Struct("<fff")

REMOTE_WORKDIR = "/userdata/rknn_yolo11_demo"
REMOTE_BINARY_BY_MODE = {
    DETECT_MODE: "./rknn_yolo11_camera_stream",
    POSE_MODE: "./rknn_yolo11_pose_camera_stream",
}
REMOTE_MODEL_BY_MODE = {
    DETECT_MODE: "model/yolo11n_rk3576.rknn",
    POSE_MODE: "model/yolo11n_pose_rk3576_fp.rknn",
}
REMOTE_DEVICE = "/dev/video42"
DEFAULT_REMOTE_LOG_BY_MODE = {
    DETECT_MODE: "/tmp/rknn_yolo11_camera_stream.log",
    POSE_MODE: "/tmp/rknn_yolo11_pose_camera_stream.log",
}

DEFAULT_SERIAL = "2e2609c37dc21c0a"
DEFAULT_WIDTH_BY_MODE = {
    DETECT_MODE: 960,
    POSE_MODE: 640,
}
DEFAULT_HEIGHT_BY_MODE = {
    DETECT_MODE: 540,
    POSE_MODE: 360,
}
DEFAULT_FPS_BY_MODE = {
    DETECT_MODE: 8,
    POSE_MODE: 5,
}
DEFAULT_SKIP = 8
DEFAULT_POSE_SCORE_THRESHOLD = 0.25

MAX_DETECTIONS = 1024
MAX_KEYPOINTS = 256
MAX_METADATA_BYTES = MAX_DETECTIONS * (BOX_STRUCT.size + MAX_KEYPOINTS * KEYPOINT_STRUCT.size)
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

COCO_POSE_EDGES = [
    (15, 13),
    (13, 11),
    (16, 14),
    (14, 12),
    (11, 12),
    (5, 11),
    (6, 12),
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (1, 2),
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),
    (3, 5),
    (4, 6),
]

POSE_EDGE_COLORS = [
    (255, 128, 0),
    (255, 153, 51),
    (255, 178, 102),
    (230, 230, 0),
    (255, 153, 255),
    (153, 204, 255),
    (255, 102, 255),
    (255, 51, 255),
    (102, 178, 255),
    (51, 153, 255),
    (255, 153, 153),
    (255, 102, 102),
    (255, 51, 51),
    (153, 255, 153),
    (102, 255, 102),
    (51, 255, 51),
    (0, 255, 0),
    (0, 0, 255),
    (255, 0, 0),
]

POSE_KEYPOINT_COLOR = (0, 255, 255)


class ProtocolError(RuntimeError):
    """Raised when the RYL1/RYP1 binary stream is malformed."""


@dataclass(slots=True)
class Detection:
    class_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    score: float


@dataclass(slots=True)
class Keypoint:
    x: float
    y: float
    score: float


@dataclass(slots=True)
class Pose:
    class_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    keypoints: list[Keypoint]


@dataclass(slots=True)
class StreamFrame:
    width: int
    height: int
    frame_index: int
    detections: list[Detection]
    payload: bytes
    poses: list[Pose] | None = None
    keypoint_count: int = 0
    flags: int = 0


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
        REMOTE_DEVICE,
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
    ]
    stream_command = shell_join(stream_parts)
    return (
        f"cd {shlex.quote(REMOTE_WORKDIR)} && "
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
    binary_name = args.remote_binary.rsplit("/", 1)[-1]
    command.extend(["shell", f"pkill -f {shlex.quote(binary_name)} 2>/dev/null || true"])
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


def protocol_mode_hint(args: argparse.Namespace, expected_magic: bytes) -> str:
    return (
        f"current --mode={args.mode} expects {expected_magic!r} from {args.remote_binary}; "
        "verify --mode matches the board-side program/protocol "
        "(detect=./rknn_yolo11_camera_stream/RYL1, "
        "pose=./rknn_yolo11_pose_camera_stream/RYP1)"
    )


def read_header(stream: BinaryIO, header_struct: struct.Struct) -> bytes | None:
    header = read_exact(stream, header_struct.size)
    if not header:
        return None
    if len(header) != header_struct.size:
        raise ProtocolError(f"short header: expected {header_struct.size} bytes, got {len(header)}")
    return header


def validate_magic(magic: bytes, expected_magic: bytes, header: bytes, args: argparse.Namespace) -> None:
    if magic != expected_magic:
        preview = header[: min(len(header), 16)].hex(" ")
        raise ProtocolError(
            f"bad magic: expected {expected_magic!r}, got {magic!r}. "
            f"{protocol_mode_hint(args, expected_magic)}. "
            f"stdout may be polluted by logs; check board log {args.remote_log}. "
            f"header preview: {preview}"
        )


def validate_frame_sizes(width: int, height: int, det_count: int, payload_size: int) -> None:
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


def read_detect_frame(stream: BinaryIO, args: argparse.Namespace) -> StreamFrame | None:
    header = read_header(stream, DETECT_HEADER_STRUCT)
    if header is None:
        return None

    magic, width, height, frame_index, det_count, payload_size = DETECT_HEADER_STRUCT.unpack(header)
    validate_magic(magic, DETECT_MAGIC, header, args)
    validate_frame_sizes(width, height, det_count, payload_size)

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


def read_pose_frame(stream: BinaryIO, args: argparse.Namespace) -> StreamFrame | None:
    header = read_header(stream, POSE_HEADER_STRUCT)
    if header is None:
        return None

    (
        magic,
        width,
        height,
        frame_index,
        det_count,
        keypoint_count,
        flags,
        meta_size,
        payload_size,
    ) = POSE_HEADER_STRUCT.unpack(header)
    validate_magic(magic, POSE_MAGIC, header, args)
    validate_frame_sizes(width, height, det_count, payload_size)

    if keypoint_count > MAX_KEYPOINTS:
        raise ProtocolError(f"invalid keypoint count: {keypoint_count} > {MAX_KEYPOINTS}")
    if meta_size > MAX_METADATA_BYTES:
        raise ProtocolError(f"pose metadata too large: {meta_size} bytes")

    pose_record_size = BOX_STRUCT.size + keypoint_count * KEYPOINT_STRUCT.size
    expected_meta_size = det_count * pose_record_size
    if meta_size != expected_meta_size:
        raise ProtocolError(
            f"pose metadata size mismatch: expected {expected_meta_size}, got {meta_size} "
            f"(det_count={det_count}, keypoint_count={keypoint_count})"
        )

    meta_bytes = read_exact(stream, meta_size)
    if len(meta_bytes) != meta_size:
        raise ProtocolError(f"short pose metadata block: expected {meta_size} bytes, got {len(meta_bytes)}")

    detections: list[Detection] = []
    poses: list[Pose] = []
    offset = 0
    for _ in range(det_count):
        class_id, score, x1, y1, x2, y2 = BOX_STRUCT.unpack_from(meta_bytes, offset)
        offset += BOX_STRUCT.size

        keypoints: list[Keypoint] = []
        for _ in range(keypoint_count):
            keypoint_x, keypoint_y, keypoint_score = KEYPOINT_STRUCT.unpack_from(meta_bytes, offset)
            offset += KEYPOINT_STRUCT.size
            keypoints.append(Keypoint(keypoint_x, keypoint_y, keypoint_score))

        detections.append(Detection(class_id, x1, y1, x2, y2, score))
        poses.append(Pose(class_id, x1, y1, x2, y2, score, keypoints))

    payload = read_exact(stream, payload_size)
    if len(payload) != payload_size:
        raise ProtocolError(f"short NV12 payload: expected {payload_size} bytes, got {len(payload)}")

    return StreamFrame(
        width,
        height,
        frame_index,
        detections,
        payload,
        poses=poses,
        keypoint_count=keypoint_count,
        flags=flags,
    )


def read_stream_frame(stream: BinaryIO, args: argparse.Namespace) -> StreamFrame | None:
    if args.mode == POSE_MODE:
        return read_pose_frame(stream, args)
    return read_detect_frame(stream, args)


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


def pose_as_detection(pose: Pose) -> Detection:
    return Detection(pose.class_id, pose.x1, pose.y1, pose.x2, pose.y2, pose.score)


def normalized_keypoints(keypoints: list[Keypoint], width: int, height: int) -> list[Keypoint | None]:
    finite_points = [
        (keypoint.x, keypoint.y)
        for keypoint in keypoints
        if math.isfinite(keypoint.x) and math.isfinite(keypoint.y)
    ]
    should_scale = False
    if finite_points:
        max_coord = max(max(abs(x), abs(y)) for x, y in finite_points)
        should_scale = max_coord <= 1.5

    normalized: list[Keypoint | None] = []
    for keypoint in keypoints:
        if not all(math.isfinite(value) for value in (keypoint.x, keypoint.y, keypoint.score)):
            normalized.append(None)
            continue

        x = keypoint.x
        y = keypoint.y
        if should_scale:
            x *= width
            y *= height

        x = max(0.0, min(float(width - 1), x))
        y = max(0.0, min(float(height - 1), y))
        normalized.append(Keypoint(x, y, keypoint.score))

    return normalized


def class_name(class_id: int) -> str:
    if 0 <= class_id < len(COCO_CLASSES):
        return COCO_CLASSES[class_id]
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


def draw_detections(image: np.ndarray, detections: list[Detection]) -> int:
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
        label = f"{class_name(detection.class_id)} {score_text}"

        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        put_label(image, label, x1, y1, color)
        drawn += 1
    return drawn


def draw_poses(image: np.ndarray, poses: list[Pose], keypoint_threshold: float) -> int:
    height, width = image.shape[:2]
    drawn = 0
    for raw_pose in poses:
        detection = normalized_box(pose_as_detection(raw_pose), width, height)
        keypoints = normalized_keypoints(raw_pose.keypoints, width, height)

        for edge_index, (start_index, end_index) in enumerate(COCO_POSE_EDGES):
            if start_index >= len(keypoints) or end_index >= len(keypoints):
                continue
            start = keypoints[start_index]
            end = keypoints[end_index]
            if start is None or end is None:
                continue
            if start.score < keypoint_threshold or end.score < keypoint_threshold:
                continue

            color = POSE_EDGE_COLORS[edge_index % len(POSE_EDGE_COLORS)]
            cv2.line(
                image,
                (int(round(start.x)), int(round(start.y))),
                (int(round(end.x)), int(round(end.y))),
                color,
                2,
                cv2.LINE_AA,
            )

        for keypoint in keypoints:
            if keypoint is None or keypoint.score < keypoint_threshold:
                continue
            cv2.circle(
                image,
                (int(round(keypoint.x)), int(round(keypoint.y))),
                3,
                POSE_KEYPOINT_COLOR,
                -1,
                cv2.LINE_AA,
            )

        if detection is None:
            continue

        color = class_color(detection.class_id)
        x1 = int(round(detection.x1))
        y1 = int(round(detection.y1))
        x2 = int(round(detection.x2))
        y2 = int(round(detection.y2))
        score = detection.score
        score_text = f"{score:.2f}" if score <= 1.0 else f"{score:.1f}"
        label = f"{class_name(detection.class_id)} {score_text}"

        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        put_label(image, label, x1, y1, color)
        drawn += 1
    return drawn


def draw_status(image: np.ndarray, mode: str, fps: float, frame_info: StreamFrame, drawn_count: int) -> None:
    text = (
        f"mode {mode} | FPS {fps:.1f} | {frame_info.width}x{frame_info.height} | "
        f"det {drawn_count} | frame {frame_info.frame_index}"
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


def score_threshold(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0 or parsed > 1.0:
        raise argparse.ArgumentTypeError("must be between 0.0 and 1.0")
    return parsed


def apply_mode_defaults(args: argparse.Namespace) -> None:
    if args.width is None:
        args.width = DEFAULT_WIDTH_BY_MODE[args.mode]
    if args.height is None:
        args.height = DEFAULT_HEIGHT_BY_MODE[args.mode]
    if args.fps is None:
        args.fps = DEFAULT_FPS_BY_MODE[args.mode]
    if args.remote_model is None:
        args.remote_model = REMOTE_MODEL_BY_MODE[args.mode]
    if args.remote_binary is None:
        args.remote_binary = REMOTE_BINARY_BY_MODE[args.mode]
    if args.remote_log is None:
        args.remote_log = DEFAULT_REMOTE_LOG_BY_MODE[args.mode]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=default_adb_path(), help="Path to adb.exe")
    parser.add_argument("--serial", default=DEFAULT_SERIAL, help="ADB serial; pass an empty string to omit -s")
    parser.add_argument(
        "--mode",
        choices=(DETECT_MODE, POSE_MODE),
        default=DETECT_MODE,
        help="Stream protocol and board-side program mode",
    )
    parser.add_argument(
        "--width",
        type=positive_int,
        help="Board camera stream width; default is 960 for detect, 640 for pose",
    )
    parser.add_argument(
        "--height",
        type=positive_int,
        help="Board camera stream height; default is 540 for detect, 360 for pose",
    )
    parser.add_argument(
        "--fps",
        type=positive_int,
        help="Board stream FPS request; default is 8 for detect, 5 for pose",
    )
    parser.add_argument("--frames", type=nonnegative_int, default=0, help="Frame count; 0 means run until stopped")
    parser.add_argument("--skip", type=nonnegative_int, default=DEFAULT_SKIP, help="Initial frames skipped by board")
    parser.add_argument(
        "--model",
        "--remote-model",
        dest="remote_model",
        help="Board-side RKNN model path; default depends on --mode",
    )
    parser.add_argument(
        "--remote-binary",
        help="Board-side stream executable; default depends on --mode",
    )
    parser.add_argument(
        "--pose-score-threshold",
        type=score_threshold,
        default=DEFAULT_POSE_SCORE_THRESHOLD,
        help="Minimum keypoint score for drawing pose points and skeleton edges",
    )
    parser.add_argument("--headless", action="store_true", help="Do not open an OpenCV window")
    parser.add_argument("--save-snapshot", type=Path, help="Save the last annotated frame")
    parser.add_argument("--window-name", default="RKNN YOLO11 IMX415 Live", help="OpenCV window title")
    parser.add_argument("--remote-log", help="Board-side stderr log path; default depends on --mode")
    args = parser.parse_args()
    apply_mode_defaults(args)

    if args.width % 2 != 0 or args.height % 2 != 0:
        parser.error("NV12 width and height must be even")
    return args


def print_headless_status(
    mode: str,
    frame_info: StreamFrame,
    fps: float,
    drawn_count: int,
    last_print: float,
) -> float:
    now = time.perf_counter()
    if now - last_print < 1.0:
        return last_print
    print(
        f"mode={mode} frame={frame_info.frame_index} fps={fps:.1f} "
        f"size={frame_info.width}x{frame_info.height} det={drawn_count}",
        file=sys.stderr,
    )
    return now


def main() -> int:
    if IMPORT_ERROR is not None:
        print(f"Missing dependency: {IMPORT_ERROR}", file=sys.stderr)
        print("Install opencv-python and numpy in the Python environment used to run this script.", file=sys.stderr)
        return 2

    args = parse_args()
    process: subprocess.Popen[bytes] | None = None
    process_started = False
    last_frame: np.ndarray | None = None
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
            frame_info = read_stream_frame(process.stdout, args)
            if frame_info is None:
                break

            frame = nv12_to_bgr(frame_info.payload, frame_info.width, frame_info.height)
            fps = fps_meter.tick()
            if args.mode == POSE_MODE:
                drawn_count = draw_poses(frame, frame_info.poses or [], args.pose_score_threshold)
            else:
                drawn_count = draw_detections(frame, frame_info.detections)
            draw_status(frame, args.mode, fps, frame_info, drawn_count)
            last_frame = frame
            frames_seen += 1

            if args.headless:
                last_headless_print = print_headless_status(
                    args.mode,
                    frame_info,
                    fps,
                    drawn_count,
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
        if adb_stderr and (exit_code != 0 or frames_seen == 0):
            print(f"ADB stderr: {adb_stderr}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

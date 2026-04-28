#!/usr/bin/env python3
"""Preview IMX415 frames from TaishanPi over ADB, optionally with YOLO ONNX."""

from __future__ import annotations

import argparse
import csv
import math
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

try:
    import onnxruntime as ort
except ImportError:  # pragma: no cover - handled at runtime
    ort = None


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


def default_adb_path() -> str:
    sdk_adb = Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe"
    return str(sdk_adb) if sdk_adb.exists() else "adb"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def candidate_models() -> list[Path]:
    ai_root = project_root() / "立创·泰山派3开发板资料" / "8.【立创·泰山派3】Ai应用"
    return [
        ai_root / "YOLO11" / "yolo11n.onnx",
        ai_root / "YOLOv8" / "yolov8n.onnx",
    ]


def find_model(model_arg: str | None) -> Path | None:
    if model_arg:
        model_path = Path(model_arg)
        return model_path if model_path.exists() else None
    for model_path in candidate_models():
        if model_path.exists():
            return model_path
    return None


def shell_quote(parts: Iterable[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def start_adb_stream(args: argparse.Namespace) -> subprocess.Popen:
    remote_parts = [
        "v4l2-ctl",
        "-d",
        args.device,
        f"--set-fmt-video=width={args.width},height={args.height},pixelformat={args.pixfmt}",
        f"--stream-mmap={args.buffers}",
        "--stream-poll",
        "--silent",
        "--stream-to=-",
    ]
    command = shell_quote(remote_parts) + " 2>/dev/null"
    adb_cmd = [args.adb]
    if args.serial:
        adb_cmd.extend(["-s", args.serial])
    adb_cmd.extend(["exec-out", "sh", "-c", command])

    return subprocess.Popen(
        adb_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )


def cleanup_remote_v4l2(args: argparse.Namespace) -> None:
    adb_cmd = [args.adb]
    if args.serial:
        adb_cmd.extend(["-s", args.serial])
    pattern = f"v4l2-ctl -d {args.device}"
    adb_cmd.extend(["shell", f"pkill -f {shlex.quote(pattern)} 2>/dev/null || true"])
    try:
        subprocess.run(adb_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
    except Exception:
        pass


def read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def nv12_to_bgr(frame_bytes: bytes, width: int, height: int) -> np.ndarray:
    expected = width * height * 3 // 2
    if len(frame_bytes) != expected:
        raise ValueError(f"expected {expected} bytes, got {len(frame_bytes)}")
    yuv = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((height * 3 // 2, width))
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)


def letterbox(image: np.ndarray, new_shape: tuple[int, int]) -> tuple[np.ndarray, float, tuple[float, float]]:
    height, width = image.shape[:2]
    target_h, target_w = new_shape
    scale = min(target_w / width, target_h / height)
    resized_w = int(round(width * scale))
    resized_h = int(round(height * scale))
    pad_w = target_w - resized_w
    pad_h = target_h - resized_h
    pad_left = pad_w / 2
    pad_top = pad_h / 2

    resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
    top = int(round(pad_top - 0.1))
    bottom = int(round(pad_top + 0.1))
    left = int(round(pad_left - 0.1))
    right = int(round(pad_left + 0.1))
    padded = cv2.copyMakeBorder(
        resized,
        top,
        bottom,
        left,
        right,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )
    return padded, scale, (pad_left, pad_top)


class YoloOnnxDetector:
    def __init__(self, model_path: Path, conf_threshold: float, iou_threshold: float) -> None:
        if ort is None:
            raise RuntimeError("onnxruntime is not installed")
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        shape = model_input.shape
        self.input_h = self._shape_dim(shape[2], 640)
        self.input_w = self._shape_dim(shape[3], 640)

    @staticmethod
    def _shape_dim(value, fallback: int) -> int:
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return fallback

    def detect(self, image: np.ndarray) -> list[tuple[int, int, int, int, float, int]]:
        prepared, scale, pad = letterbox(image, (self.input_h, self.input_w))
        rgb = cv2.cvtColor(prepared, cv2.COLOR_BGR2RGB)
        tensor = rgb.astype(np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
        outputs = self.session.run(None, {self.input_name: tensor})
        return self._postprocess(outputs[0], image.shape[:2], scale, pad)

    def _postprocess(
        self,
        output: np.ndarray,
        image_shape: tuple[int, int],
        scale: float,
        pad: tuple[float, float],
    ) -> list[tuple[int, int, int, int, float, int]]:
        pred = np.asarray(output)
        if pred.ndim == 3:
            pred = pred[0]
        if pred.ndim != 2:
            return []
        if pred.shape[0] < pred.shape[1] and pred.shape[0] in (84, 85, 116):
            pred = pred.T

        if pred.shape[1] < 6:
            return []
        boxes_xywh = pred[:, :4]
        if pred.shape[1] == 85:
            objectness = pred[:, 4]
            class_scores = pred[:, 5:]
            class_ids = np.argmax(class_scores, axis=1)
            confidences = objectness * class_scores[np.arange(class_scores.shape[0]), class_ids]
        else:
            class_scores = pred[:, 4:]
            class_ids = np.argmax(class_scores, axis=1)
            confidences = class_scores[np.arange(class_scores.shape[0]), class_ids]

        keep = confidences >= self.conf_threshold
        boxes_xywh = boxes_xywh[keep]
        confidences = confidences[keep]
        class_ids = class_ids[keep]
        if boxes_xywh.size == 0:
            return []

        image_h, image_w = image_shape
        pad_x, pad_y = pad
        boxes: list[list[int]] = []
        for cx, cy, bw, bh in boxes_xywh:
            x1 = (cx - bw / 2 - pad_x) / scale
            y1 = (cy - bh / 2 - pad_y) / scale
            x2 = (cx + bw / 2 - pad_x) / scale
            y2 = (cy + bh / 2 - pad_y) / scale
            x1 = max(0, min(image_w - 1, x1))
            y1 = max(0, min(image_h - 1, y1))
            x2 = max(0, min(image_w - 1, x2))
            y2 = max(0, min(image_h - 1, y2))
            boxes.append([int(x1), int(y1), int(max(0, x2 - x1)), int(max(0, y2 - y1))])

        indices = cv2.dnn.NMSBoxes(
            boxes,
            confidences.astype(float).tolist(),
            self.conf_threshold,
            self.iou_threshold,
        )
        if len(indices) == 0:
            return []

        detections = []
        for index in np.array(indices).reshape(-1):
            x, y, w, h = boxes[int(index)]
            detections.append(
                (
                    x,
                    y,
                    x + w,
                    y + h,
                    float(confidences[int(index)]),
                    int(class_ids[int(index)]),
                )
            )
        return detections


def draw_detections(image: np.ndarray, detections: list[tuple[int, int, int, int, float, int]]) -> None:
    for x1, y1, x2, y2, score, class_id in detections:
        name = COCO_CLASSES[class_id] if 0 <= class_id < len(COCO_CLASSES) else str(class_id)
        label = f"{name} {score:.2f}"
        cv2.rectangle(image, (x1, y1), (x2, y2), (40, 220, 40), 2)
        text_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        text_w, text_h = text_size
        y_text = max(text_h + baseline, y1)
        cv2.rectangle(
            image,
            (x1, y_text - text_h - baseline),
            (x1 + text_w + 4, y_text + baseline),
            (40, 220, 40),
            -1,
        )
        cv2.putText(
            image,
            label,
            (x1 + 2, y_text - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )


def frame_metrics(frame: np.ndarray, previous: np.ndarray | None) -> dict[str, float]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    focus = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    b_mean, g_mean, r_mean, _ = cv2.mean(frame)
    diff = 0.0
    if previous is not None and previous.shape == frame.shape:
        diff = float(cv2.absdiff(frame, previous).mean())
    return {
        "focus": focus,
        "y_mean": float(gray.mean()),
        "y_std": float(gray.std()),
        "b_mean": float(b_mean),
        "g_mean": float(g_mean),
        "r_mean": float(r_mean),
        "frame_delta": diff,
    }


def draw_metrics(frame: np.ndarray, metrics: dict[str, float]) -> None:
    lines = [
        f"focus {metrics['focus']:.1f}",
        f"Y {metrics['y_mean']:.1f} std {metrics['y_std']:.1f}",
        f"BGR {metrics['b_mean']:.0f}/{metrics['g_mean']:.0f}/{metrics['r_mean']:.0f}",
        f"delta {metrics['frame_delta']:.2f}",
    ]
    y = 28
    for line in lines:
        cv2.putText(
            frame,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        y += 28


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=default_adb_path(), help="Path to adb.exe")
    parser.add_argument("--serial", default="2e2609c37dc21c0a", help="ADB serial")
    parser.add_argument("--device", default="/dev/video42", help="Board V4L2 output node")
    parser.add_argument("--width", type=int, default=960, help="Capture width")
    parser.add_argument("--height", type=int, default=540, help="Capture height")
    parser.add_argument("--pixfmt", default="NV12", help="V4L2 pixel format")
    parser.add_argument("--buffers", type=int, default=4, help="V4L2 mmap buffer count")
    parser.add_argument("--frames", type=int, default=0, help="Frame count, 0 means run until stopped")
    parser.add_argument("--warmup-frames", type=int, default=8, help="Discard initial frames while 3A converges")
    parser.add_argument("--headless", action="store_true", help="Do not open an OpenCV window")
    parser.add_argument("--save-snapshot", type=Path, help="Save the last displayed frame")
    parser.add_argument("--model", type=str, help="YOLOv8/YOLO11 ONNX model path")
    parser.add_argument("--no-detect", action="store_true", help="Disable YOLO detection")
    parser.add_argument("--conf", type=float, default=0.35, help="Detection confidence threshold")
    parser.add_argument("--iou", type=float, default=0.45, help="NMS IoU threshold")
    parser.add_argument("--display-scale", type=float, default=1.0, help="Scale GUI display frame")
    parser.add_argument("--diagnostics", action="store_true", help="Overlay focus and exposure stability metrics")
    parser.add_argument("--metrics-csv", type=Path, help="Write per-frame focus/exposure metrics to CSV")
    return parser.parse_args()


def make_detector(args: argparse.Namespace) -> YoloOnnxDetector | None:
    if args.no_detect:
        return None
    model_path = find_model(args.model)
    if model_path is None:
        print("No YOLO ONNX model found; running preview only.", file=sys.stderr)
        return None
    try:
        detector = YoloOnnxDetector(model_path, args.conf, args.iou)
    except Exception as exc:  # noqa: BLE001 - degrade to preview instead of failing
        print(f"Failed to load {model_path}: {exc}; running preview only.", file=sys.stderr)
        return None
    print(f"Loaded model: {model_path}", file=sys.stderr)
    return detector


def save_snapshot(path: Path, frame: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"failed to write {path}")


def main() -> int:
    args = parse_args()
    frame_size = args.width * args.height * 3 // 2
    detector = make_detector(args)
    process = start_adb_stream(args)
    last_frame: np.ndarray | None = None
    previous_frame: np.ndarray | None = None
    metrics_file = None
    metrics_writer = None
    frame_count = 0
    raw_frame_count = 0
    started = time.perf_counter()

    try:
        if args.metrics_csv:
            args.metrics_csv.parent.mkdir(parents=True, exist_ok=True)
            metrics_file = args.metrics_csv.open("w", newline="", encoding="utf-8")
            metrics_writer = csv.DictWriter(
                metrics_file,
                fieldnames=[
                    "frame",
                    "timestamp",
                    "focus",
                    "y_mean",
                    "y_std",
                    "b_mean",
                    "g_mean",
                    "r_mean",
                    "frame_delta",
                ],
            )
            metrics_writer.writeheader()
        assert process.stdout is not None
        while True:
            raw_frame = read_exact(process.stdout, frame_size)
            if len(raw_frame) == 0:
                break
            if len(raw_frame) != frame_size:
                print(f"Short frame: expected {frame_size}, got {len(raw_frame)}", file=sys.stderr)
                break

            frame = nv12_to_bgr(raw_frame, args.width, args.height)
            raw_frame_count += 1
            if raw_frame_count <= args.warmup_frames:
                previous_frame = None
                continue

            metrics = frame_metrics(frame, previous_frame)
            if metrics_writer is not None:
                metrics_writer.writerow({"frame": frame_count, "timestamp": time.time(), **metrics})
            previous_frame = frame.copy() if args.diagnostics or metrics_writer is not None else None
            if detector is not None:
                detections = detector.detect(frame)
                draw_detections(frame, detections)
                cv2.putText(
                    frame,
                    f"detections: {len(detections)}",
                    (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (30, 230, 30),
                    2,
                    cv2.LINE_AA,
                )
            if args.diagnostics:
                draw_metrics(frame, metrics)

            frame_count += 1
            elapsed = max(1e-6, time.perf_counter() - started)
            cv2.putText(
                frame,
                f"{args.device} {args.width}x{args.height} {frame_count / elapsed:.1f} fps",
                (12, frame.shape[0] - 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            last_frame = frame

            if not args.headless:
                shown = frame
                if not math.isclose(args.display_scale, 1.0):
                    shown = cv2.resize(frame, None, fx=args.display_scale, fy=args.display_scale)
                cv2.imshow("TaishanPi IMX415 YOLO Preview", shown)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break

            if args.frames > 0 and frame_count >= args.frames:
                break
    finally:
        if metrics_file is not None:
            metrics_file.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        cleanup_remote_v4l2(args)
        if not args.headless:
            cv2.destroyAllWindows()

    if args.save_snapshot and last_frame is not None:
        save_snapshot(args.save_snapshot, last_frame)
        print(f"Saved snapshot: {args.save_snapshot}")

    if frame_count == 0:
        stderr = b""
        if process.stderr is not None:
            try:
                stderr = process.stderr.read(4096)
            except Exception:
                stderr = b""
        if stderr:
            print(stderr.decode(errors="replace"), file=sys.stderr)
        print(f"No processed frames received. Raw frames read: {raw_frame_count}.", file=sys.stderr)
        return 1

    print(f"Processed {frame_count} frame(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

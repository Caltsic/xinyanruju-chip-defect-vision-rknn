#!/usr/bin/env python3
"""Run the exported chip-defect ONNX model on saved frames for quick diagnosis."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = (
    ROOT
    / "cloud_training"
    / "autodl_outputs_20260502"
    / "outputs"
    / "final"
    / "chipcheck_yolov8_detect.onnx"
)
DEFAULT_IMAGE_DIR = ROOT / "captures" / "practice"
DEFAULT_SAVE_DIR = ROOT / "captures" / "practice_onnx_diag"
CLASS_NAMES = ["ZF-scratch", "scratch", "broken", "pinbreak"]
BOX_COLORS = [(56, 56, 255), (10, 249, 72), (255, 194, 0), (255, 56, 132)]


@dataclass(slots=True)
class Detection:
    class_id: int
    score: float
    box: np.ndarray


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"failed to read image: {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix or ".jpg", image)
    if not ok:
        raise RuntimeError(f"failed to encode image: {path}")
    encoded.tofile(str(path))


def letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, float, int, int]:
    height, width = image.shape[:2]
    scale = min(size / height, size / width)
    resized_width = int(round(width * scale))
    resized_height = int(round(height * scale))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    x_pad = (size - resized_width) // 2
    y_pad = (size - resized_height) // 2
    canvas[y_pad : y_pad + resized_height, x_pad : x_pad + resized_width] = resized
    return canvas, scale, x_pad, y_pad


def box_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    box_area = np.maximum(0.0, box[2] - box[0]) * np.maximum(0.0, box[3] - box[1])
    boxes_area = np.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0.0, boxes[:, 3] - boxes[:, 1])
    return inter / np.maximum(box_area + boxes_area - inter, 1e-6)


def nms(boxes: np.ndarray, scores: np.ndarray, classes: np.ndarray, threshold: float) -> list[int]:
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        current = int(order[0])
        keep.append(current)
        rest = order[1:]
        if rest.size == 0:
            break
        same_class = classes[rest] == classes[current]
        overlaps = box_iou(boxes[current], boxes[rest])
        order = rest[~(same_class & (overlaps > threshold))]
    return keep


def infer(
    session: ort.InferenceSession,
    input_name: str,
    image: np.ndarray,
    image_size: int,
    conf: float,
    nms_threshold: float,
) -> list[Detection]:
    model_input, scale, x_pad, y_pad = letterbox(image, image_size)
    rgb = cv2.cvtColor(model_input, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    tensor = np.transpose(rgb, (2, 0, 1))[None]
    output = np.squeeze(session.run(None, {input_name: tensor})[0])
    predictions = output.T if output.shape[0] == len(CLASS_NAMES) + 4 else output

    class_scores = predictions[:, 4 : 4 + len(CLASS_NAMES)]
    classes = class_scores.argmax(axis=1)
    scores = class_scores.max(axis=1)
    valid = scores > conf
    if not np.any(valid):
        return []

    boxes = predictions[valid, :4].astype(np.float32)
    classes = classes[valid]
    scores = scores[valid]

    xyxy = np.empty_like(boxes)
    xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] * 0.5
    xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] * 0.5
    xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] * 0.5
    xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] * 0.5
    xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] - x_pad) / scale
    xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] - y_pad) / scale
    xyxy[:, [0, 2]] = np.clip(xyxy[:, [0, 2]], 0, image.shape[1] - 1)
    xyxy[:, [1, 3]] = np.clip(xyxy[:, [1, 3]], 0, image.shape[0] - 1)

    keep = nms(xyxy, scores, classes, nms_threshold)
    return [Detection(int(classes[i]), float(scores[i]), xyxy[i]) for i in keep]


def draw(image: np.ndarray, detections: list[Detection]) -> np.ndarray:
    out = image.copy()
    for det in detections:
        color = BOX_COLORS[det.class_id % len(BOX_COLORS)]
        x1, y1, x2, y2 = [int(round(value)) for value in det.box.tolist()]
        label = f"{CLASS_NAMES[det.class_id]} {det.score:.2f}"
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        text_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        text_w, text_h = text_size
        y_text = max(text_h + baseline + 4, y1)
        cv2.rectangle(out, (x1, y_text - text_h - baseline - 4), (x1 + text_w + 6, y_text + baseline), color, -1)
        cv2.putText(out, label, (x1 + 3, y_text - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)
    return out


def collect_images(paths: list[Path]) -> list[Path]:
    if paths:
        return paths
    patterns = ("*.png", "*.jpg", "*.jpeg", "*.bmp")
    images: list[Path] = []
    for pattern in patterns:
        images.extend(DEFAULT_IMAGE_DIR.glob(pattern))
    return sorted(images)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="*", type=Path, help="Images to diagnose; defaults to captures/practice")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Exported ONNX model path")
    parser.add_argument("--imgsz", type=int, default=640, help="Model input size")
    parser.add_argument("--conf", type=float, default=0.25, help="Primary confidence threshold")
    parser.add_argument("--probe-conf", type=float, default=0.05, help="Low threshold used to reveal weak candidates")
    parser.add_argument("--nms", type=float, default=0.45, help="NMS IoU threshold")
    parser.add_argument("--save-dir", type=Path, default=DEFAULT_SAVE_DIR, help="Directory for annotated outputs")
    parser.add_argument("--no-save", action="store_true", help="Do not save annotated outputs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_paths = collect_images(args.images)
    if not image_paths:
        print(f"no images found in {DEFAULT_IMAGE_DIR}")
        return 2

    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    print(f"model={args.model}")
    print(f"images={len(image_paths)} conf={args.conf:.3f} probe_conf={args.probe_conf:.3f}")

    for path in image_paths:
        image = read_image(path)
        detections = infer(session, input_name, image, args.imgsz, args.conf, args.nms)
        weak_detections = infer(session, input_name, image, args.imgsz, args.probe_conf, args.nms)
        summary = ", ".join(f"{CLASS_NAMES[d.class_id]}:{d.score:.2f}" for d in detections[:5]) or "-"
        weak_summary = ", ".join(f"{CLASS_NAMES[d.class_id]}:{d.score:.2f}" for d in weak_detections[:5]) or "-"
        print(f"{path.name}: det@{args.conf:.2f}={len(detections)} [{summary}] weak@{args.probe_conf:.2f}={len(weak_detections)} [{weak_summary}]")

        if not args.no_save:
            annotated = draw(image, detections if detections else weak_detections)
            output_path = args.save_dir / f"{path.stem}_onnx_diag.jpg"
            write_image(output_path, annotated)

    if not args.no_save:
        print(f"saved={args.save_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

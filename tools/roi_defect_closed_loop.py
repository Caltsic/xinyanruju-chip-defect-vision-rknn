#!/usr/bin/env python3
"""Chip ROI -> light preprocessing -> chip-defect ONNX closed loop.

This is a PC-side minimum validation path. It uses the existing camera capture
path only to get a clean frame, then runs ROI localization and ONNX inference
locally so the ROI/preprocess logic can be iterated quickly before moving it to
the board-side RKNN pipeline.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
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
DEFAULT_CHIP_MODEL = (
    ROOT
    / "cloud_training"
    / "chip_roi_outputs_20260504"
    / "outputs"
    / "final"
    / "chip_roi_yolov8_detect.onnx"
)
DEFAULT_SAVE_DIR = ROOT / "captures" / "roi_defect_closed_loop"
LIVE_VIEW_SCRIPT = ROOT / "tools" / "adb_imx415_rknn_live_view.py"

CLASS_NAMES = ["ZF-scratch", "scratch", "broken", "pinbreak"]
CHIP_CLASS_NAMES = ["chip"]
BOX_COLORS = [(56, 56, 255), (10, 249, 72), (255, 194, 0), (255, 56, 132)]


@dataclass(slots=True)
class Detection:
    class_id: int
    score: float
    box: np.ndarray
    source: str


@dataclass(slots=True)
class RoiResult:
    box: tuple[int, int, int, int]
    score: float
    method: str


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


def parse_roi(text: str) -> tuple[int, int, int, int]:
    parts = [int(part.strip()) for part in text.replace(";", ",").split(",") if part.strip()]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ROI must be x,y,w,h")
    x, y, width, height = parts
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("ROI width and height must be positive")
    return x, y, x + width, y + height


def clamp_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(0, min(width, x2))
    y2 = max(0, min(height, y2))
    if x2 <= x1:
        x2 = min(width, x1 + 1)
    if y2 <= y1:
        y2 = min(height, y1 + 1)
    return x1, y1, x2, y2


def square_expand_box(
    box: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
    margin: float,
    min_side: int,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5
    side = max(x2 - x1, y2 - y1)
    side = max(float(min_side), side * (1.0 + 2.0 * margin))
    sx1 = int(round(cx - side * 0.5))
    sy1 = int(round(cy - side * 0.5))
    sx2 = int(round(cx + side * 0.5))
    sy2 = int(round(cy + side * 0.5))

    if sx1 < 0:
        sx2 -= sx1
        sx1 = 0
    if sy1 < 0:
        sy2 -= sy1
        sy1 = 0
    if sx2 > image_width:
        shift = sx2 - image_width
        sx1 = max(0, sx1 - shift)
        sx2 = image_width
    if sy2 > image_height:
        shift = sy2 - image_height
        sy1 = max(0, sy1 - shift)
        sy2 = image_height
    return clamp_box((sx1, sy1, sx2, sy2), image_width, image_height)


def locate_chip_roi(image: np.ndarray, margin: float, min_side: int) -> RoiResult:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    border_size_y = max(4, height // 24)
    border_size_x = max(4, width // 24)
    border = np.concatenate(
        [
            blur[:border_size_y, :].ravel(),
            blur[-border_size_y:, :].ravel(),
            blur[:, :border_size_x].ravel(),
            blur[:, -border_size_x:].ravel(),
        ]
    )
    bg = float(np.median(border))
    threshold = max(28.0, min(bg - 24.0, float(np.percentile(blur, 42))))
    dark_mask = (blur < threshold).astype(np.uint8) * 255

    # Red text and dark vignette can create edge components. Keep the full mask,
    # but scoring below heavily penalizes border and top-left overlay hits.
    edges = cv2.Canny(blur, 45, 135)
    mask = cv2.bitwise_or(dark_mask, cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8), iterations=2)
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    center_x = width * 0.5
    center_y = height * 0.5
    image_area = float(width * height)

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area_ratio = (w * h) / image_area
        if area_ratio < 0.0015 or area_ratio > 0.22:
            continue
        if w < 18 or h < 18:
            continue

        touches_border = x <= 2 or y <= 2 or x + w >= width - 2 or y + h >= height - 2
        cx = x + w * 0.5
        cy = y + h * 0.5
        center_distance = ((cx - center_x) / width) ** 2 + ((cy - center_y) / height) ** 2
        aspect = max(w / max(h, 1), h / max(w, 1))
        if aspect > 4.0:
            continue

        roi_gray = gray[y : y + h, x : x + w]
        darkness = max(1.0, 255.0 - float(np.mean(roi_gray)))
        border_penalty = 0.18 if touches_border else 1.0
        overlay_penalty = 0.25 if (x < width * 0.35 and y < height * 0.14) else 1.0
        centrality = 1.0 / (1.0 + 12.0 * center_distance)
        score = area_ratio * darkness * centrality * border_penalty * overlay_penalty
        candidates.append((score, (x, y, x + w, y + h)))

    if candidates:
        score, raw_box = max(candidates, key=lambda item: item[0])
        expanded = square_expand_box(raw_box, width, height, margin, min_side)
        return RoiResult(expanded, score, "auto-dark-edge")

    fallback_side = max(min_side, int(round(min(width, height) * 0.42)))
    fallback = square_expand_box(
        (
            int(round(center_x - fallback_side * 0.5)),
            int(round(center_y - fallback_side * 0.5)),
            int(round(center_x + fallback_side * 0.5)),
            int(round(center_y + fallback_side * 0.5)),
        ),
        width,
        height,
        0.0,
        fallback_side,
    )
    return RoiResult(fallback, 0.0, "fallback-center")


def locate_chip_roi_model(
    image: np.ndarray,
    session: ort.InferenceSession,
    input_name: str,
    image_size: int,
    conf: float,
    nms_threshold: float,
    margin: float,
    min_side: int,
) -> RoiResult | None:
    detections = infer(
        session,
        input_name,
        image,
        image_size,
        conf,
        nms_threshold,
        "chip-yolov8",
        class_count=len(CHIP_CLASS_NAMES),
    )
    if not detections:
        return None

    image_height, image_width = image.shape[:2]
    center_x = image_width * 0.5
    center_y = image_height * 0.5

    def rank(det: Detection) -> float:
        x1, y1, x2, y2 = det.box.tolist()
        cx = (x1 + x2) * 0.5
        cy = (y1 + y2) * 0.5
        center_distance = ((cx - center_x) / image_width) ** 2 + ((cy - center_y) / image_height) ** 2
        return det.score / (1.0 + 3.0 * center_distance)

    best = max(detections, key=rank)
    x1, y1, x2, y2 = [int(round(value)) for value in best.box.tolist()]
    expanded = square_expand_box((x1, y1, x2, y2), image_width, image_height, margin, min_side)
    return RoiResult(expanded, best.score, "chip-yolov8")


def gamma_light(image: np.ndarray, gamma: float = 0.88) -> np.ndarray:
    lut = np.array([round(((value / 255.0) ** gamma) * 255.0) for value in range(256)], dtype=np.uint8)
    return cv2.LUT(image, lut)


def lab_clahe(image: np.ndarray, clip_limit: float = 1.4) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    return cv2.cvtColor(cv2.merge([l_channel, a_channel, b_channel]), cv2.COLOR_LAB2BGR)


def mild_sharpen(image: np.ndarray, amount: float = 0.18) -> np.ndarray:
    blurred = cv2.GaussianBlur(image, (0, 0), 1.0)
    return cv2.addWeighted(image, 1.0 + amount, blurred, -amount, 0)


def build_variant(name: str, crop: np.ndarray) -> np.ndarray:
    if name == "raw":
        return crop.copy()
    if name == "light_gamma_clahe":
        return lab_clahe(gamma_light(crop, 0.88), 1.4)
    if name == "light_clahe_sharp":
        return mild_sharpen(lab_clahe(crop, 1.4), 0.20)
    if name == "clahe_l":
        return lab_clahe(crop, 1.6)
    raise ValueError(f"unknown preprocess variant: {name}")


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


def classwise_nms(detections: list[Detection], threshold: float) -> list[Detection]:
    if not detections:
        return []
    boxes = np.stack([det.box for det in detections]).astype(np.float32)
    scores = np.array([det.score for det in detections], dtype=np.float32)
    classes = np.array([det.class_id for det in detections], dtype=np.int32)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        current = int(order[0])
        keep.append(current)
        rest = order[1:]
        if rest.size == 0:
            break
        overlaps = box_iou(boxes[current], boxes[rest])
        same_class = classes[rest] == classes[current]
        order = rest[~(same_class & (overlaps > threshold))]
    return [detections[index] for index in keep]


def infer(
    session: ort.InferenceSession,
    input_name: str,
    image: np.ndarray,
    image_size: int,
    conf: float,
    nms_threshold: float,
    source: str,
    class_count: int | None = None,
) -> list[Detection]:
    class_count = class_count or len(CLASS_NAMES)
    model_input, scale, x_pad, y_pad = letterbox(image, image_size)
    rgb = cv2.cvtColor(model_input, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    tensor = np.transpose(rgb, (2, 0, 1))[None]
    raw_output = session.run(None, {input_name: tensor})[0]
    output = np.squeeze(raw_output)
    if output.ndim != 2:
        raise RuntimeError(f"unsupported YOLO output shape: {raw_output.shape}")
    if output.shape[0] == class_count + 4:
        predictions = output.T
    elif output.shape[1] >= class_count + 4:
        predictions = output
    else:
        raise RuntimeError(
            f"unsupported YOLO output shape: {raw_output.shape}; expected {class_count + 4} channels"
        )

    class_scores = predictions[:, 4 : 4 + class_count]
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

    detections = [
        Detection(int(class_id), float(score), box.astype(np.float32), source)
        for class_id, score, box in zip(classes, scores, xyxy)
    ]
    return classwise_nms(detections, nms_threshold)


def map_detections_to_full(
    detections: list[Detection],
    roi_box: tuple[int, int, int, int],
) -> list[Detection]:
    x_offset, y_offset, _, _ = roi_box
    mapped: list[Detection] = []
    for det in detections:
        box = det.box.copy()
        box[[0, 2]] += x_offset
        box[[1, 3]] += y_offset
        mapped.append(Detection(det.class_id, det.score, box, det.source))
    return mapped


def put_label(image: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
    text_size, baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
    text_w, text_h = text_size
    x = max(0, min(x, max(0, image.shape[1] - text_w - 8)))
    y = max(text_h + baseline + 4, y)
    cv2.rectangle(image, (x, y - text_h - baseline - 4), (x + text_w + 6, y + baseline), color, -1)
    cv2.putText(image, text, (x + 3, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)


def draw_alignment_guides(image: np.ndarray, roi: RoiResult) -> None:
    height, width = image.shape[:2]
    x1, y1, x2, y2 = roi.box
    frame_center = (width // 2, height // 2)
    chip_center = (int(round((x1 + x2) * 0.5)), int(round((y1 + y2) * 0.5)))
    dx = chip_center[0] - frame_center[0]
    dy = chip_center[1] - frame_center[1]
    side_ratio = max(x2 - x1, y2 - y1) / max(1, min(width, height))
    center_ok = abs(dx) <= width * 0.05 and abs(dy) <= height * 0.05
    size_ok = 0.30 <= side_ratio <= 0.72
    color = (80, 255, 160) if center_ok and size_ok else (0, 220, 255)

    cv2.drawMarker(image, frame_center, color, cv2.MARKER_CROSS, 36, 2, cv2.LINE_AA)
    cv2.circle(image, chip_center, 5, color, -1, cv2.LINE_AA)
    cv2.line(image, chip_center, frame_center, color, 2, cv2.LINE_AA)
    put_label(
        image,
        f"chip dx={dx:+d}px dy={dy:+d}px size={side_ratio:.2f}",
        12,
        height - 16,
        color,
    )


def draw_result(
    image: np.ndarray,
    roi: RoiResult,
    detections: list[Detection],
    conf: float,
) -> np.ndarray:
    out = image.copy()
    x1, y1, x2, y2 = roi.box
    cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 255), 2)
    draw_alignment_guides(out, roi)

    strong = [det for det in detections if det.score >= conf]
    for index, det in enumerate(strong, start=1):
        color = BOX_COLORS[det.class_id % len(BOX_COLORS)]
        bx1, by1, bx2, by2 = [int(round(value)) for value in det.box.tolist()]
        cv2.rectangle(out, (bx1, by1), (bx2, by2), color, 2)
        put_label(out, str(index), bx1, by1, color)

    legend_lines = [f"ROI {roi.method} {roi.score:.2f}"]
    legend_lines.extend(
        f"{index}. {CLASS_NAMES[det.class_id]} {det.score:.2f} {det.source}"
        for index, det in enumerate(strong[:8], start=1)
    )
    legend_x = 12
    legend_y = 72
    for line_index, line in enumerate(legend_lines):
        color = (0, 255, 255) if line_index == 0 else BOX_COLORS[strong[line_index - 1].class_id % len(BOX_COLORS)]
        put_label(out, line, legend_x, legend_y + line_index * 26, color)
    return out


def make_contact_sheet(items: list[tuple[str, np.ndarray]], path: Path) -> None:
    if not items:
        return
    tile_w = 240
    tile_h = 220
    cols = min(3, len(items))
    rows = (len(items) + cols - 1) // cols
    sheet = np.full((rows * tile_h, cols * tile_w, 3), 235, dtype=np.uint8)
    for index, (name, image) in enumerate(items):
        tile = cv2.resize(image, (tile_w, tile_h), interpolation=cv2.INTER_AREA)
        cv2.rectangle(tile, (0, 0), (tile_w - 1, 25), (255, 255, 255), -1)
        cv2.putText(tile, name[:28], (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        row = index // cols
        col = index % cols
        sheet[row * tile_h : (row + 1) * tile_h, col * tile_w : (col + 1) * tile_w] = tile
    write_image(path, sheet)


def capture_maixcam(args: argparse.Namespace) -> Path:
    output = args.capture_path
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(LIVE_VIEW_SCRIPT),
        "--profile",
        "chip-defect-maixcam",
        "--frames",
        str(args.capture_frames),
        "--headless",
        "--conf",
        "0.99",
        "--save-clean-snapshot",
        str(output),
        "--remote-log",
        args.remote_log,
    ]
    if args.adb:
        command.extend(["--adb", args.adb])
    if args.serial:
        command.extend(["--serial", args.serial])
    if args.device:
        command.extend(["--device", args.device])
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"MaixCAM capture failed with exit code {result.returncode}")
    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError(f"MaixCAM capture did not create {output}; /dev/video73 may be busy")
    return output


def process_image(
    image_path: Path,
    args: argparse.Namespace,
    session: ort.InferenceSession,
    input_name: str,
    chip_session: ort.InferenceSession | None,
    chip_input_name: str | None,
) -> list[Detection]:
    image = read_image(image_path)
    image_height, image_width = image.shape[:2]
    if args.roi:
        roi_box = clamp_box(args.roi, image_width, image_height)
        roi = RoiResult(roi_box, 1.0, "manual")
    else:
        roi = None
        if chip_session is not None and chip_input_name is not None:
            roi = locate_chip_roi_model(
                image,
                chip_session,
                chip_input_name,
                args.chip_imgsz,
                args.chip_conf,
                args.chip_nms,
                args.roi_margin,
                args.roi_min_side,
            )
            if roi is None:
                print(f"{image_path.name}: chip-yolov8 found no ROI; fallback to dark-edge")
        if roi is None:
            roi = locate_chip_roi(image, args.roi_margin, args.roi_min_side)

    x1, y1, x2, y2 = roi.box
    crop = image[y1:y2, x1:x2].copy()
    variants = [name.strip() for name in args.variants.split(",") if name.strip()]
    all_mapped: list[Detection] = []
    contact_items: list[tuple[str, np.ndarray]] = []

    for variant_name in variants:
        variant = build_variant(variant_name, crop)
        detections = infer(
            session,
            input_name,
            variant,
            args.imgsz,
            args.probe_conf,
            args.nms,
            variant_name,
            class_count=len(CLASS_NAMES),
        )
        mapped = map_detections_to_full(detections, roi.box)
        all_mapped.extend(mapped)

        if not args.no_save_crops:
            crop_path = args.save_dir / f"{image_path.stem}_{variant_name}_crop.jpg"
            write_image(crop_path, variant)
            variant_draw = draw_result(
                np.pad(variant, ((0, 0), (0, 0), (0, 0)), mode="constant"),
                RoiResult((0, 0, variant.shape[1], variant.shape[0]), 1.0, variant_name),
                detections,
                args.conf,
            )
            contact_items.append((variant_name, variant_draw))

        top = ", ".join(
            f"{CLASS_NAMES[det.class_id]}:{det.score:.3f}"
            for det in detections[: args.top_k]
        ) or "-"
        strong = sum(1 for det in detections if det.score >= args.conf)
        print(f"{image_path.name} {variant_name}: det@{args.conf:.3f}={strong} top=[{top}]")

    merged = classwise_nms(all_mapped, args.merge_nms)
    strong_merged = [det for det in merged if det.score >= args.conf]
    summary = ", ".join(
        f"{CLASS_NAMES[det.class_id]}:{det.score:.3f}/{det.source}"
        for det in strong_merged[: args.top_k]
    ) or "-"
    print(
        f"{image_path.name}: roi={roi.box} method={roi.method} "
        f"merged@{args.conf:.3f}={len(strong_merged)} [{summary}]"
    )

    if not args.no_save:
        annotated = draw_result(image, roi, merged, args.conf)
        write_image(args.save_dir / f"{image_path.stem}_roi_closed_loop.jpg", annotated)
        if contact_items:
            make_contact_sheet(contact_items, args.save_dir / f"{image_path.stem}_variants.jpg")

    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="*", type=Path, help="Images to process")
    parser.add_argument("--capture-maixcam", action="store_true", help="Capture one MaixCAM frame before processing")
    parser.add_argument("--capture-path", type=Path, help="Clean frame path for --capture-maixcam")
    parser.add_argument("--capture-frames", type=int, default=8, help="Frames requested from MaixCAM capture helper")
    parser.add_argument("--adb", default="", help="Optional adb.exe path override for capture helper")
    parser.add_argument("--serial", default="2e2609c37dc21c0a", help="ADB serial for capture helper")
    parser.add_argument("--device", default="/dev/video73", help="Board V4L2 node for capture helper")
    parser.add_argument("--remote-log", default="/tmp/rknn_maixcam_roi_capture.log", help="Board log path for capture helper")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="ONNX chip defect model")
    parser.add_argument("--imgsz", type=int, default=640, help="ONNX input size")
    parser.add_argument("--chip-model", type=Path, default=DEFAULT_CHIP_MODEL, help="ONNX chip ROI model")
    parser.add_argument("--chip-imgsz", type=int, default=640, help="Chip ROI ONNX input size")
    parser.add_argument("--chip-conf", type=float, default=0.25, help="Chip ROI confidence threshold")
    parser.add_argument("--chip-nms", type=float, default=0.45, help="Chip ROI NMS threshold")
    parser.add_argument("--no-chip-model", action="store_true", help="Disable trained chip ROI model and use dark-edge ROI")
    parser.add_argument("--conf", type=float, default=0.05, help="Reported/drawn confidence threshold")
    parser.add_argument("--probe-conf", type=float, default=0.001, help="Low threshold for per-variant probing")
    parser.add_argument("--nms", type=float, default=0.45, help="NMS threshold inside each variant")
    parser.add_argument("--merge-nms", type=float, default=0.45, help="NMS threshold when merging variants")
    parser.add_argument("--variants", default="raw,light_gamma_clahe", help="Comma-separated variants")
    parser.add_argument("--roi", type=parse_roi, help="Manual ROI x,y,w,h; otherwise auto-locate chip")
    parser.add_argument("--roi-margin", type=float, default=0.35, help="Expansion margin around auto chip box")
    parser.add_argument("--roi-min-side", type=int, default=220, help="Minimum square ROI side")
    parser.add_argument("--save-dir", type=Path, default=DEFAULT_SAVE_DIR, help="Output directory")
    parser.add_argument("--top-k", type=int, default=6, help="Number of top detections to print")
    parser.add_argument("--no-save", action="store_true", help="Do not save annotated full-frame outputs")
    parser.add_argument("--no-save-crops", action="store_true", help="Do not save crop variants/contact sheets")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.save_dir.mkdir(parents=True, exist_ok=True)
    if args.capture_path is None:
        args.capture_path = args.save_dir / "maixcam_current_clean.jpg"
    image_paths = list(args.images)
    if args.capture_maixcam:
        image_paths.append(capture_maixcam(args))
    if not image_paths:
        raise SystemExit("provide images or pass --capture-maixcam")

    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    chip_session: ort.InferenceSession | None = None
    chip_input_name: str | None = None
    if not args.no_chip_model:
        if args.chip_model.exists():
            chip_session = ort.InferenceSession(str(args.chip_model), providers=["CPUExecutionProvider"])
            chip_input_name = chip_session.get_inputs()[0].name
        else:
            print(f"chip_model_missing={args.chip_model}; fallback=dark-edge")
    print(f"model={args.model}")
    if chip_session is not None:
        print(f"chip_model={args.chip_model} chip_conf={args.chip_conf:.3f}")
    print(f"variants={args.variants} conf={args.conf:.3f} probe_conf={args.probe_conf:.3f}")

    for image_path in image_paths:
        process_image(image_path, args, session, input_name, chip_session, chip_input_name)

    print(f"saved={args.save_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

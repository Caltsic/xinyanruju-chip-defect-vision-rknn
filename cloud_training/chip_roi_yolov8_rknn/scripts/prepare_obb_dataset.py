#!/usr/bin/env python3
"""Prepare a one-class YOLO OBB dataset from chip ROI YOLO HBB labels.

Input labels are standard 5-column YOLO detection labels:

    class cx cy w h

Output labels are YOLO OBB 9-column labels:

    class x1 y1 x2 y2 x3 y3 x4 y4

The converter estimates an oriented rectangle near each HBB crop with OpenCV
minAreaRect. If no stable rotated rectangle is found, it writes the horizontal
box as four points so every valid HBB object remains trainable.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


SPLITS = ("train", "valid", "test")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
CLASS_NAMES = ["chip"]


@dataclass
class SplitStats:
    images: int = 0
    labels: int = 0
    objects: int = 0
    auto_rects: int = 0
    fallback_rects: int = 0
    empty_label_files: int = 0
    class_counts: dict[int, int] = field(default_factory=dict)


@dataclass
class PrepareStats:
    source: str
    output: str
    image_mode: str
    splits: dict[str, SplitStats] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dataset", required=True, type=Path, help="Source dataset root with train/valid/test.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Output YOLO OBB dataset root.")
    parser.add_argument("--calib-output", type=Path, help="Path for RKNN calibration image list.")
    parser.add_argument("--labels-output", type=Path, help="Path for chip ROI labels txt.")
    parser.add_argument("--calib-count", type=int, default=300, help="Number of calibration images to sample.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for calibration and preview sampling.")
    parser.add_argument("--padding-ratio", type=float, default=0.18, help="Extra crop padding around each HBB.")
    parser.add_argument("--min-contour-area-ratio", type=float, default=0.18, help="Reject tiny contour candidates.")
    parser.add_argument("--preview-count", type=int, default=0, help="Write this many OBB preview images per split.")
    parser.add_argument("--preview-dir", type=Path, help="Preview output directory. Defaults to output-dir/preview.")
    parser.add_argument("--self-check", action="store_true", help="Validate generated OBB labels after conversion.")
    parser.add_argument(
        "--image-mode",
        choices=("hardlink", "copy", "symlink"),
        default="hardlink",
        help="How to place images in the converted dataset.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output directory.")
    return parser.parse_args()


def ensure_clean_output(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {path}. Use --overwrite to replace it.")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def iter_images(images_dir: Path) -> list[Path]:
    files: list[Path] = []
    for ext in IMAGE_EXTS:
        files.extend(images_dir.glob(f"*{ext}"))
        files.extend(images_dir.glob(f"*{ext.upper()}"))
    return sorted(set(files))


def link_or_copy(src: Path, dst: Path, mode: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "copy":
        shutil.copy2(src, dst)
        return
    if mode == "symlink":
        try:
            dst.symlink_to(src.resolve())
            return
        except OSError:
            shutil.copy2(src, dst)
            return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def parse_label_line(line: str, label_path: Path, line_no: int) -> tuple[int, float, float, float, float] | None:
    parts = line.split()
    if not parts:
        return None
    if len(parts) != 5:
        raise ValueError(f"{label_path}:{line_no}: expected YOLO bbox with 5 columns, got {len(parts)}")
    try:
        cls_float = float(parts[0])
        values = [float(value) for value in parts[1:]]
    except ValueError as exc:
        raise ValueError(f"{label_path}:{line_no}: non-numeric label value") from exc
    cls_id = int(cls_float)
    if cls_id != cls_float or cls_id != 0:
        raise ValueError(f"{label_path}:{line_no}: class id must be 0 for chip ROI, got {parts[0]}")
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ValueError(f"{label_path}:{line_no}: coordinate outside [0, 1]")
    cx, cy, width, height = values
    if width <= 0.0 or height <= 0.0:
        raise ValueError(f"{label_path}:{line_no}: non-positive bbox size")
    return cls_id, cx, cy, width, height


def yolo_hbb_to_pixels(cx: float, cy: float, width: float, height: float, image_w: int, image_h: int) -> tuple[float, float, float, float]:
    box_w = width * image_w
    box_h = height * image_h
    x1 = cx * image_w - box_w / 2.0
    y1 = cy * image_h - box_h / 2.0
    x2 = cx * image_w + box_w / 2.0
    y2 = cy * image_h + box_h / 2.0
    return clip_box(x1, y1, x2, y2, image_w, image_h)


def clip_box(x1: float, y1: float, x2: float, y2: float, image_w: int, image_h: int) -> tuple[float, float, float, float]:
    x1 = max(0.0, min(float(image_w - 1), x1))
    y1 = max(0.0, min(float(image_h - 1), y1))
    x2 = max(0.0, min(float(image_w - 1), x2))
    y2 = max(0.0, min(float(image_h - 1), y2))
    return x1, y1, x2, y2


def horizontal_quad(x1: float, y1: float, x2: float, y2: float) -> np.ndarray:
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float32)


def order_quad(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    ordered = pts[np.argsort(angles)]
    start = int(np.argmin(ordered.sum(axis=1)))
    return np.roll(ordered, -start, axis=0)


def clip_quad(points: np.ndarray, image_w: int, image_h: int) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).copy()
    pts[:, 0] = np.clip(pts[:, 0], 0.0, float(image_w - 1))
    pts[:, 1] = np.clip(pts[:, 1], 0.0, float(image_h - 1))
    return pts


def quad_area(points: np.ndarray) -> float:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    return float(abs(cv2.contourArea(pts)))


def build_candidate_masks(gray: np.ndarray) -> list[np.ndarray]:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    masks: list[np.ndarray] = []
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    masks.append(otsu)
    masks.append(cv2.bitwise_not(otsu))

    edges = cv2.Canny(blurred, 40, 120)
    kernel = np.ones((3, 3), np.uint8)
    masks.append(cv2.dilate(edges, kernel, iterations=1))

    cleaned: list[np.ndarray] = []
    for mask in masks:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        cleaned.append(mask)
    return cleaned


def estimate_obb(
    image: np.ndarray,
    hbb: tuple[float, float, float, float],
    padding_ratio: float,
    min_contour_area_ratio: float,
) -> tuple[np.ndarray, str]:
    image_h, image_w = image.shape[:2]
    x1, y1, x2, y2 = hbb
    box_w = max(1.0, x2 - x1)
    box_h = max(1.0, y2 - y1)
    pad = max(box_w, box_h) * max(0.0, padding_ratio)
    cx1, cy1, cx2, cy2 = clip_box(x1 - pad, y1 - pad, x2 + pad, y2 + pad, image_w, image_h)
    ix1, iy1 = int(math.floor(cx1)), int(math.floor(cy1))
    ix2, iy2 = int(math.ceil(cx2)), int(math.ceil(cy2))
    if ix2 <= ix1 + 3 or iy2 <= iy1 + 3:
        return horizontal_quad(x1, y1, x2, y2), "fallback_small_crop"

    crop = image[iy1 : iy2 + 1, ix1 : ix2 + 1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    min_area = box_w * box_h * max(0.01, min_contour_area_ratio)
    max_area = crop.shape[0] * crop.shape[1] * 0.98
    crop_center = np.array([crop.shape[1] / 2.0, crop.shape[0] / 2.0], dtype=np.float32)

    best_quad: np.ndarray | None = None
    best_score = -1.0
    for mask in build_candidate_masks(gray):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area or area > max_area:
                continue
            rect = cv2.minAreaRect(contour)
            (rw, rh) = rect[1]
            if rw < 3.0 or rh < 3.0:
                continue
            quad = cv2.boxPoints(rect).astype(np.float32)
            rect_center = quad.mean(axis=0)
            center_dist = float(np.linalg.norm(rect_center - crop_center))
            score = float(area) - center_dist * max(box_w, box_h) * 0.08
            if score > best_score:
                best_quad = quad
                best_score = score

    if best_quad is None:
        return horizontal_quad(x1, y1, x2, y2), "fallback_no_contour"

    best_quad[:, 0] += ix1
    best_quad[:, 1] += iy1
    best_quad = order_quad(clip_quad(best_quad, image_w, image_h))
    if quad_area(best_quad) < min_area:
        return horizontal_quad(x1, y1, x2, y2), "fallback_tiny_rect"
    return best_quad, "auto_min_area_rect"


def format_obb_line(cls_id: int, quad: np.ndarray, image_w: int, image_h: int) -> str:
    pts = clip_quad(order_quad(quad), image_w, image_h)
    values: list[float] = []
    for x, y in pts:
        values.append(float(np.clip(x / image_w, 0.0, 1.0)))
        values.append(float(np.clip(y / image_h, 0.0, 1.0)))
    return f"{cls_id} " + " ".join(f"{value:.8f}" for value in values)


def convert_label_file(
    src: Path,
    dst: Path,
    image_path: Path,
    stats: SplitStats,
    args: argparse.Namespace,
) -> list[np.ndarray]:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"OpenCV failed to read image: {image_path}")
    image_h, image_w = image.shape[:2]

    lines = src.read_text(encoding="utf-8").splitlines()
    converted: list[str] = []
    quads: list[np.ndarray] = []
    for line_no, raw_line in enumerate(lines, start=1):
        parsed = parse_label_line(raw_line.strip(), src, line_no)
        if parsed is None:
            continue
        cls_id, cx, cy, width, height = parsed
        hbb = yolo_hbb_to_pixels(cx, cy, width, height, image_w, image_h)
        quad, method = estimate_obb(image, hbb, args.padding_ratio, args.min_contour_area_ratio)
        if method == "auto_min_area_rect":
            stats.auto_rects += 1
        else:
            stats.fallback_rects += 1
        converted.append(format_obb_line(cls_id, quad, image_w, image_h))
        quads.append(quad)
        stats.objects += 1
        stats.class_counts[cls_id] = stats.class_counts.get(cls_id, 0) + 1

    if not converted:
        stats.empty_label_files += 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(converted) + ("\n" if converted else ""), encoding="utf-8")
    return quads


def write_data_yaml(output_dir: Path) -> None:
    names_lines = "\n".join(f"  {idx}: {name}" for idx, name in enumerate(CLASS_NAMES))
    content = f"""path: {output_dir.resolve().as_posix()}
train: train/images
val: valid/images
test: test/images
nc: {len(CLASS_NAMES)}
names:
{names_lines}
"""
    (output_dir / "data.yaml").write_text(content, encoding="utf-8")


def write_labels(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(CLASS_NAMES) + "\n", encoding="utf-8")


def write_calib_list(output_dir: Path, calib_output: Path, calib_count: int, seed: int) -> None:
    candidates = iter_images(output_dir / "train" / "images")
    if not candidates:
        raise RuntimeError("No train images available for calibration list.")
    rng = random.Random(seed)
    sample_count = min(max(calib_count, 1), len(candidates))
    selected = sorted(rng.sample(candidates, sample_count))
    calib_output.parent.mkdir(parents=True, exist_ok=True)
    calib_output.write_text("\n".join(path.resolve().as_posix() for path in selected) + "\n", encoding="utf-8")


def validate_obb_dataset(output_dir: Path) -> dict[str, int]:
    checked_files = 0
    checked_objects = 0
    for split in SPLITS:
        for label_path in sorted((output_dir / split / "labels").glob("*.txt")):
            checked_files += 1
            for line_no, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
                parts = line.split()
                if not parts:
                    continue
                if len(parts) != 9:
                    raise ValueError(f"{label_path}:{line_no}: expected 9 OBB columns, got {len(parts)}")
                cls_id = int(float(parts[0]))
                coords = [float(value) for value in parts[1:]]
                if cls_id != 0:
                    raise ValueError(f"{label_path}:{line_no}: class id must be 0, got {cls_id}")
                if any(value < 0.0 or value > 1.0 for value in coords):
                    raise ValueError(f"{label_path}:{line_no}: OBB coordinate outside [0, 1]")
                checked_objects += 1
    return {"checked_label_files": checked_files, "checked_objects": checked_objects}


def draw_preview(image_path: Path, label_path: Path, output_path: Path) -> None:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        return
    image_h, image_w = image.shape[:2]
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 9:
            continue
        coords = [float(value) for value in parts[1:]]
        pts = np.array(
            [[coords[idx] * image_w, coords[idx + 1] * image_h] for idx in range(0, 8, 2)],
            dtype=np.int32,
        )
        cv2.polylines(image, [pts], isClosed=True, color=(0, 0, 255), thickness=2)
        x, y, w, h = cv2.boundingRect(pts)
        cv2.rectangle(image, (x, y), (x + w, y + h), (0, 180, 0), 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), image)


def write_previews(output_dir: Path, preview_dir: Path, count: int, seed: int) -> dict[str, int]:
    if count <= 0:
        return {}
    rng = random.Random(seed)
    written: dict[str, int] = {}
    for split in SPLITS:
        images = iter_images(output_dir / split / "images")
        labeled = [path for path in images if (output_dir / split / "labels" / f"{path.stem}.txt").exists()]
        selected = sorted(rng.sample(labeled, min(count, len(labeled))))
        for image_path in selected:
            label_path = output_dir / split / "labels" / f"{image_path.stem}.txt"
            draw_preview(image_path, label_path, preview_dir / split / image_path.name)
        written[split] = len(selected)
    return written


def prepare_dataset(args: argparse.Namespace) -> PrepareStats:
    raw_root = args.raw_dataset.resolve()
    out_root = args.output_dir.resolve()
    if not raw_root.exists():
        raise FileNotFoundError(f"Raw dataset does not exist: {raw_root}")
    ensure_clean_output(out_root, args.overwrite)

    stats = PrepareStats(source=str(raw_root), output=str(out_root), image_mode=args.image_mode)
    for split in SPLITS:
        split_stats = SplitStats()
        stats.splits[split] = split_stats
        src_images = raw_root / split / "images"
        src_labels = raw_root / split / "labels"
        dst_images = out_root / split / "images"
        dst_labels = out_root / split / "labels"
        if not src_images.exists() or not src_labels.exists():
            raise FileNotFoundError(f"Missing images/labels directory for split {split}")

        images = iter_images(src_images)
        labels = sorted(src_labels.glob("*.txt"))
        split_stats.images = len(images)
        split_stats.labels = len(labels)
        image_stems = {path.stem for path in images}
        label_stems = {path.stem for path in labels}
        missing_labels = sorted(image_stems - label_stems)
        missing_images = sorted(label_stems - image_stems)
        if missing_labels or missing_images:
            raise RuntimeError(
                f"Split {split} has pairing errors: "
                f"{len(missing_labels)} missing labels, {len(missing_images)} missing images"
            )

        image_by_stem = {path.stem: path for path in images}
        for image_path in images:
            link_or_copy(image_path, dst_images / image_path.name, args.image_mode)
        for label_path in labels:
            convert_label_file(
                label_path,
                dst_labels / label_path.name,
                image_by_stem[label_path.stem],
                split_stats,
                args,
            )

    write_data_yaml(out_root)
    labels_output = args.labels_output or out_root / "chip_roi_labels.txt"
    calib_output = args.calib_output or out_root / "calib_dataset.txt"
    write_labels(labels_output.resolve())
    write_calib_list(out_root, calib_output.resolve(), args.calib_count, args.seed)

    check_report = validate_obb_dataset(out_root) if args.self_check else {}
    preview_dir = (args.preview_dir or out_root / "preview").resolve()
    preview_report = write_previews(out_root, preview_dir, args.preview_count, args.seed)

    report_path = out_root / "dataset_report.json"
    report = {
        "source": stats.source,
        "output": stats.output,
        "format": "yolo_obb_8point",
        "source_format": "yolo_hbb_5column",
        "image_mode": stats.image_mode,
        "class_names": CLASS_NAMES,
        "obb_estimator": {
            "method": "opencv_minAreaRect_near_hbb_crop",
            "fallback": "horizontal_four_points",
            "padding_ratio": args.padding_ratio,
            "min_contour_area_ratio": args.min_contour_area_ratio,
        },
        "splits": {
            split: {
                "images": split_stats.images,
                "labels": split_stats.labels,
                "objects": split_stats.objects,
                "auto_rects": split_stats.auto_rects,
                "fallback_rects": split_stats.fallback_rects,
                "empty_label_files": split_stats.empty_label_files,
                "class_counts": split_stats.class_counts,
            }
            for split, split_stats in stats.splits.items()
        },
        "calib_dataset": str(calib_output.resolve()),
        "labels": str(labels_output.resolve()),
        "data_yaml": str((out_root / "data.yaml").resolve()),
        "self_check": check_report,
        "preview": {"dir": str(preview_dir), "written": preview_report} if args.preview_count > 0 else {},
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return stats


def main() -> None:
    args = parse_args()
    stats = prepare_dataset(args)
    total_images = sum(split.images for split in stats.splits.values())
    total_objects = sum(split.objects for split in stats.splits.values())
    total_auto = sum(split.auto_rects for split in stats.splits.values())
    total_fallback = sum(split.fallback_rects for split in stats.splits.values())
    print(f"Prepared chip ROI OBB dataset: {stats.output}")
    print(f"Images: {total_images}, objects: {total_objects}, auto_rects={total_auto}, fallback_rects={total_fallback}")
    for split, split_stats in stats.splits.items():
        print(
            f"{split}: images={split_stats.images}, labels={split_stats.labels}, "
            f"objects={split_stats.objects}, auto_rects={split_stats.auto_rects}, "
            f"fallback_rects={split_stats.fallback_rects}, empty_labels={split_stats.empty_label_files}"
        )


if __name__ == "__main__":
    main()

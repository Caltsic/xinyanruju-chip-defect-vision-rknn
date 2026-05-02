#!/usr/bin/env python3
"""Prepare the chip defect dataset for YOLOv8 detection training.

The source dataset mixes YOLO detection labels and YOLO segmentation polygon
labels. This script creates a separate detection-only dataset and never
overwrites the raw labels.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path


SPLITS = ("train", "valid", "test")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
CLASS_NAMES = ["ZF-scratch", "scratch", "broken", "pinbreak"]


@dataclass
class SplitStats:
    images: int = 0
    labels: int = 0
    objects: int = 0
    bbox_objects: int = 0
    polygon_objects: int = 0
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
    parser.add_argument("--output-dir", required=True, type=Path, help="Output YOLOv8 detection dataset root.")
    parser.add_argument("--calib-output", type=Path, help="Path for RKNN calibration image list.")
    parser.add_argument("--labels-output", type=Path, help="Path for chip defect labels txt.")
    parser.add_argument("--calib-count", type=int, default=300, help="Number of calibration images to sample.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for calibration sampling.")
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


def clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def parse_label_line(line: str, label_path: Path, line_no: int) -> tuple[int, float, float, float, float, str] | None:
    parts = line.split()
    if not parts:
        return None
    try:
        cls_float = float(parts[0])
    except ValueError as exc:
        raise ValueError(f"{label_path}:{line_no}: invalid class id {parts[0]!r}") from exc
    cls_id = int(cls_float)
    if cls_id != cls_float or not 0 <= cls_id < len(CLASS_NAMES):
        raise ValueError(f"{label_path}:{line_no}: class id out of range: {parts[0]}")
    try:
        values = [float(value) for value in parts[1:]]
    except ValueError as exc:
        raise ValueError(f"{label_path}:{line_no}: non-numeric coordinate") from exc
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ValueError(f"{label_path}:{line_no}: coordinate outside [0, 1]")

    if len(parts) == 5:
        cx, cy, width, height = values
        cx, cy = clamp01(cx), clamp01(cy)
        width, height = clamp01(width), clamp01(height)
        if width <= 0.0 or height <= 0.0:
            raise ValueError(f"{label_path}:{line_no}: non-positive bbox size")
        return cls_id, cx, cy, width, height, "bbox"

    if len(values) >= 6 and len(values) % 2 == 0:
        xs = values[0::2]
        ys = values[1::2]
        x_min, x_max = clamp01(min(xs)), clamp01(max(xs))
        y_min, y_max = clamp01(min(ys)), clamp01(max(ys))
        width = x_max - x_min
        height = y_max - y_min
        if width <= 0.0 or height <= 0.0:
            raise ValueError(f"{label_path}:{line_no}: polygon collapsed to empty bbox")
        cx = (x_min + x_max) / 2.0
        cy = (y_min + y_max) / 2.0
        return cls_id, cx, cy, width, height, "polygon"

    raise ValueError(f"{label_path}:{line_no}: unsupported label format with {len(parts)} columns")


def convert_label_file(src: Path, dst: Path, stats: SplitStats) -> None:
    lines = src.read_text(encoding="utf-8").splitlines()
    converted: list[str] = []
    for line_no, raw_line in enumerate(lines, start=1):
        parsed = parse_label_line(raw_line.strip(), src, line_no)
        if parsed is None:
            continue
        cls_id, cx, cy, width, height, kind = parsed
        converted.append(f"{cls_id} {cx:.8f} {cy:.8f} {width:.8f} {height:.8f}")
        stats.objects += 1
        stats.class_counts[cls_id] = stats.class_counts.get(cls_id, 0) + 1
        if kind == "bbox":
            stats.bbox_objects += 1
        else:
            stats.polygon_objects += 1
    if not converted:
        stats.empty_label_files += 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(converted) + ("\n" if converted else ""), encoding="utf-8")


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

        for image_path in images:
            link_or_copy(image_path, dst_images / image_path.name, args.image_mode)
        for label_path in labels:
            convert_label_file(label_path, dst_labels / label_path.name, split_stats)

    write_data_yaml(out_root)
    labels_output = args.labels_output or out_root / "chip_defect_labels.txt"
    calib_output = args.calib_output or out_root / "calib_dataset.txt"
    write_labels(labels_output.resolve())
    write_calib_list(out_root, calib_output.resolve(), args.calib_count, args.seed)

    report_path = out_root / "dataset_report.json"
    report = {
        "source": stats.source,
        "output": stats.output,
        "image_mode": stats.image_mode,
        "class_names": CLASS_NAMES,
        "splits": {
            split: {
                "images": split_stats.images,
                "labels": split_stats.labels,
                "objects": split_stats.objects,
                "bbox_objects": split_stats.bbox_objects,
                "polygon_objects": split_stats.polygon_objects,
                "empty_label_files": split_stats.empty_label_files,
                "class_counts": split_stats.class_counts,
            }
            for split, split_stats in stats.splits.items()
        },
        "calib_dataset": str(calib_output.resolve()),
        "labels": str(labels_output.resolve()),
        "data_yaml": str((out_root / "data.yaml").resolve()),
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return stats


def main() -> None:
    args = parse_args()
    stats = prepare_dataset(args)
    total_images = sum(split.images for split in stats.splits.values())
    total_objects = sum(split.objects for split in stats.splits.values())
    print(f"Prepared detection dataset: {stats.output}")
    print(f"Images: {total_images}, objects: {total_objects}")
    for split, split_stats in stats.splits.items():
        print(
            f"{split}: images={split_stats.images}, labels={split_stats.labels}, "
            f"objects={split_stats.objects}, bbox={split_stats.bbox_objects}, "
            f"polygon={split_stats.polygon_objects}, empty_labels={split_stats.empty_label_files}"
        )


if __name__ == "__main__":
    main()

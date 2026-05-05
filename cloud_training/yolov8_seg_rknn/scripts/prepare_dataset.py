#!/usr/bin/env python3
"""Prepare a YOLOv8 segmentation dataset while preserving polygon labels.

The source labels may mix YOLO bbox lines and YOLO segmentation polygon lines.
By default this script keeps only polygon objects. Images whose labels contain
only bbox objects are skipped and counted in dataset_report.json.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


SPLITS = ("train", "valid", "test")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
DEFAULT_CLASS_NAMES = ["ZF-scratch", "scratch", "broken", "pinbreak"]


@dataclass
class SplitStats:
    source_images: int = 0
    source_labels: int = 0
    kept_images: int = 0
    skipped_bbox_only_images: int = 0
    skipped_empty_label_images: int = 0
    skipped_missing_label_images: int = 0
    polygon_objects: int = 0
    bbox_objects_skipped: int = 0
    empty_output_label_files: int = 0
    class_counts: dict[int, int] = field(default_factory=dict)
    skipped_bbox_only_files: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dataset", required=True, type=Path, help="Source dataset root with train/valid/test.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Output YOLOv8 segmentation dataset root.")
    parser.add_argument("--calib-output", type=Path, help="Path for RKNN calibration image list.")
    parser.add_argument("--labels-output", type=Path, help="Path for class labels txt.")
    parser.add_argument("--class-names", nargs="+", help="Class names. Defaults to names.yaml or chip defect classes.")
    parser.add_argument("--names-yaml", type=Path, help="Optional dataset names.yaml/data.yaml used to load class names.")
    parser.add_argument("--calib-count", type=int, default=300, help="Number of calibration images to sample.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for calibration sampling.")
    parser.add_argument(
        "--image-mode",
        choices=("hardlink", "copy", "symlink"),
        default="hardlink",
        help="How to place images in the converted dataset.",
    )
    parser.add_argument("--keep-empty-images", action="store_true", help="Keep images with no polygon labels as negatives.")
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


def load_class_names(args: argparse.Namespace) -> list[str]:
    if args.class_names:
        return list(args.class_names)
    candidates = [args.names_yaml] if args.names_yaml else []
    candidates.extend([args.raw_dataset / "names.yaml", args.raw_dataset / "data.yaml"])
    for path in candidates:
        if not path or not path.exists():
            continue
        if yaml is None:
            raise SystemExit("Missing dependency: install PyYAML to read names.yaml.")
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        names = data.get("names", data)
        if isinstance(names, dict):
            ordered_keys = sorted(names, key=lambda key: int(key) if str(key).isdigit() else str(key))
            return [str(names[idx]) for idx in ordered_keys]
        if isinstance(names, list):
            return [str(name) for name in names]
    return DEFAULT_CLASS_NAMES


def parse_label_line(line: str, label_path: Path, line_no: int, class_count: int) -> tuple[int, list[float], str] | None:
    parts = line.split()
    if not parts:
        return None
    try:
        cls_float = float(parts[0])
    except ValueError as exc:
        raise ValueError(f"{label_path}:{line_no}: invalid class id {parts[0]!r}") from exc
    cls_id = int(cls_float)
    if cls_id != cls_float or not 0 <= cls_id < class_count:
        raise ValueError(f"{label_path}:{line_no}: class id out of range: {parts[0]}")
    try:
        values = [float(value) for value in parts[1:]]
    except ValueError as exc:
        raise ValueError(f"{label_path}:{line_no}: non-numeric coordinate") from exc
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ValueError(f"{label_path}:{line_no}: coordinate outside [0, 1]")
    if len(values) == 4:
        return cls_id, values, "bbox"
    if len(values) >= 6 and len(values) % 2 == 0:
        return cls_id, values, "polygon"
    raise ValueError(f"{label_path}:{line_no}: unsupported label format with {len(parts)} columns")


def convert_label_file(src: Path, dst: Path, stats: SplitStats, class_count: int) -> bool:
    polygon_lines: list[str] = []
    bbox_count = 0
    for line_no, raw_line in enumerate(src.read_text(encoding="utf-8").splitlines(), start=1):
        parsed = parse_label_line(raw_line.strip(), src, line_no, class_count)
        if parsed is None:
            continue
        cls_id, values, kind = parsed
        if kind == "bbox":
            bbox_count += 1
            continue
        polygon_lines.append(" ".join([str(cls_id), *(f"{value:.8f}" for value in values)]))
        stats.polygon_objects += 1
        stats.class_counts[cls_id] = stats.class_counts.get(cls_id, 0) + 1

    stats.bbox_objects_skipped += bbox_count
    if not polygon_lines:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(polygon_lines) + "\n", encoding="utf-8")
    return True


def write_data_yaml(output_dir: Path, class_names: list[str]) -> None:
    names_lines = "\n".join(f"  {idx}: {name}" for idx, name in enumerate(class_names))
    content = f"""path: {output_dir.resolve().as_posix()}
train: train/images
val: valid/images
test: test/images
nc: {len(class_names)}
names:
{names_lines}
"""
    (output_dir / "data.yaml").write_text(content, encoding="utf-8")


def write_labels(path: Path, class_names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(class_names) + "\n", encoding="utf-8")


def write_calib_list(output_dir: Path, calib_output: Path, calib_count: int, seed: int) -> None:
    candidates = iter_images(output_dir / "train" / "images")
    if not candidates:
        raise RuntimeError("No train images available for calibration list.")
    rng = random.Random(seed)
    selected = sorted(rng.sample(candidates, min(max(calib_count, 1), len(candidates))))
    calib_output.parent.mkdir(parents=True, exist_ok=True)
    calib_output.write_text("\n".join(path.resolve().as_posix() for path in selected) + "\n", encoding="utf-8")


def prepare_dataset(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = args.raw_dataset.resolve()
    out_root = args.output_dir.resolve()
    if not raw_root.exists():
        raise FileNotFoundError(f"Raw dataset does not exist: {raw_root}")
    ensure_clean_output(out_root, args.overwrite)

    class_names = load_class_names(args)
    split_reports: dict[str, SplitStats] = {}

    for split in SPLITS:
        split_stats = SplitStats()
        split_reports[split] = split_stats
        src_images = raw_root / split / "images"
        src_labels = raw_root / split / "labels"
        dst_images = out_root / split / "images"
        dst_labels = out_root / split / "labels"
        if not src_images.exists() or not src_labels.exists():
            raise FileNotFoundError(f"Missing images/labels directory for split {split}")

        images = iter_images(src_images)
        labels_by_stem = {path.stem: path for path in src_labels.glob("*.txt")}
        split_stats.source_images = len(images)
        split_stats.source_labels = len(labels_by_stem)

        for image_path in images:
            label_path = labels_by_stem.get(image_path.stem)
            if label_path is None:
                split_stats.skipped_missing_label_images += 1
                if not args.keep_empty_images:
                    continue
                link_or_copy(image_path, dst_images / image_path.name, args.image_mode)
                (dst_labels / f"{image_path.stem}.txt").parent.mkdir(parents=True, exist_ok=True)
                (dst_labels / f"{image_path.stem}.txt").write_text("", encoding="utf-8")
                split_stats.empty_output_label_files += 1
                split_stats.kept_images += 1
                continue

            label_dst = dst_labels / label_path.name
            had_polygon = convert_label_file(label_path, label_dst, split_stats, len(class_names))
            if had_polygon:
                link_or_copy(image_path, dst_images / image_path.name, args.image_mode)
                split_stats.kept_images += 1
                continue

            raw_nonempty = any(line.strip() for line in label_path.read_text(encoding="utf-8").splitlines())
            if raw_nonempty:
                split_stats.skipped_bbox_only_images += 1
                split_stats.skipped_bbox_only_files.append(label_path.name)
            else:
                split_stats.skipped_empty_label_images += 1
            if args.keep_empty_images:
                link_or_copy(image_path, dst_images / image_path.name, args.image_mode)
                label_dst.parent.mkdir(parents=True, exist_ok=True)
                label_dst.write_text("", encoding="utf-8")
                split_stats.empty_output_label_files += 1
                split_stats.kept_images += 1

    write_data_yaml(out_root, class_names)
    labels_output = (args.labels_output or out_root / "chip_defect_seg_labels.txt").resolve()
    calib_output = (args.calib_output or out_root / "calib_dataset.txt").resolve()
    write_labels(labels_output, class_names)
    write_calib_list(out_root, calib_output, args.calib_count, args.seed)

    report = {
        "source": str(raw_root),
        "output": str(out_root),
        "task": "segment",
        "image_mode": args.image_mode,
        "keep_empty_images": bool(args.keep_empty_images),
        "class_names": class_names,
        "splits": {
            split: {
                "source_images": stats.source_images,
                "source_labels": stats.source_labels,
                "kept_images": stats.kept_images,
                "skipped_bbox_only_images": stats.skipped_bbox_only_images,
                "skipped_empty_label_images": stats.skipped_empty_label_images,
                "skipped_missing_label_images": stats.skipped_missing_label_images,
                "polygon_objects": stats.polygon_objects,
                "bbox_objects_skipped": stats.bbox_objects_skipped,
                "empty_output_label_files": stats.empty_output_label_files,
                "class_counts": stats.class_counts,
                "skipped_bbox_only_files": stats.skipped_bbox_only_files[:200],
            }
            for split, stats in split_reports.items()
        },
        "calib_dataset": str(calib_output),
        "labels": str(labels_output),
        "data_yaml": str((out_root / "data.yaml").resolve()),
    }
    (out_root / "dataset_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    args = parse_args()
    report = prepare_dataset(args)
    total_kept = sum(split["kept_images"] for split in report["splits"].values())
    total_poly = sum(split["polygon_objects"] for split in report["splits"].values())
    total_bbox_skip = sum(split["bbox_objects_skipped"] for split in report["splits"].values())
    print(f"Prepared segmentation dataset: {report['output']}")
    print(f"Kept images: {total_kept}, polygon objects: {total_poly}, skipped bbox objects: {total_bbox_skip}")
    for split, stats in report["splits"].items():
        print(
            f"{split}: kept={stats['kept_images']}, polygon={stats['polygon_objects']}, "
            f"bbox_only_images={stats['skipped_bbox_only_images']}, empty={stats['skipped_empty_label_images']}"
        )


if __name__ == "__main__":
    main()

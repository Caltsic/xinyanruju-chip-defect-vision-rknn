#!/usr/bin/env python3
"""Prepare a one-class YOLO OBB dataset from CVAT COCO polygon exports.

The chip locator is trained as an oriented-box model. Manual CVAT polygons are
treated as correction handles, then regularized with OpenCV minAreaRect before
writing YOLO OBB labels:

    class x1 y1 x2 y2 x3 y3 x4 y4

Non-quad polygons are skipped by default so accidental 5+ point chip masks do
not enter the OBB training set.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
SPLITS = ("train", "valid", "test")
CLASS_NAMES = ["chip"]


@dataclass
class ObjectRecord:
    points: list[tuple[float, float]]
    annotation_id: int | str


@dataclass
class ImageRecord:
    image_id: int
    file_name: str
    image_path: Path
    width: int
    height: int
    objects: list[ObjectRecord] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="CVAT COCO export zip or extracted directory.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Output YOLO OBB dataset root.")
    parser.add_argument("--calib-output", type=Path, help="RKNN calibration image list output.")
    parser.add_argument("--labels-output", type=Path, help="Class labels txt output.")
    parser.add_argument("--calib-count", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.85)
    parser.add_argument("--valid-ratio", type=float, default=0.10)
    parser.add_argument("--test-ratio", type=float, default=0.05)
    parser.add_argument("--image-mode", choices=("copy", "hardlink", "symlink"), default="hardlink")
    parser.add_argument("--drop-non-quad", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-area", type=float, default=4.0, help="Drop regularized boxes below this pixel area.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def ensure_clean_output(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {path}. Use --overwrite to replace it.")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def extract_input(input_path: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if input_path.is_dir():
        return input_path.resolve(), None
    if not input_path.is_file() or input_path.suffix.lower() != ".zip":
        raise FileNotFoundError(f"Input must be a CVAT COCO zip or directory: {input_path}")
    temp_dir = tempfile.TemporaryDirectory(prefix="chip_obb_cvat_")
    root = Path(temp_dir.name)
    with zipfile.ZipFile(input_path, "r") as archive:
        archive.extractall(root)
    return root, temp_dir


def iter_coco_jsons(root: Path) -> list[Path]:
    candidates = [
        path
        for path in root.rglob("*.json")
        if "instances" in path.name.lower() or "annotation" in path.name.lower()
    ]
    return sorted(candidates)


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"failed to read image: {path}")
    return image


def write_jpeg(path: Path, image: np.ndarray, quality: int = 95) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError(f"failed to encode image: {path}")
    path.write_bytes(encoded.tobytes())


def build_image_index(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            index.setdefault(path.name, []).append(path)
            rel = path.relative_to(root).as_posix()
            index.setdefault(rel, []).append(path)
    return index


def resolve_image_path(root: Path, image_index: dict[str, list[Path]], file_name: str) -> Path | None:
    raw = Path(file_name)
    candidates = [
        root / raw,
        root / "images" / raw,
        root / "images" / "default" / raw,
        root / "images" / "default" / raw.name,
        root / raw.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for key in (file_name, raw.as_posix(), raw.name):
        paths = image_index.get(key)
        if paths:
            return sorted(paths, key=lambda p: len(str(p)))[0]
    return None


def category_mapping(coco: dict[str, Any]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for category in coco.get("categories", []):
        cat_id = int(category["id"])
        name = str(category.get("name", ""))
        if name == "chip" or cat_id == 1:
            mapping[cat_id] = 0
    return mapping


def polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    last_x, last_y = points[-1]
    for x, y in points:
        area += last_x * y - x * last_y
        last_x, last_y = x, y
    return abs(area) * 0.5


def parse_polygon(segmentation: Any) -> list[tuple[float, float]] | None:
    if not isinstance(segmentation, list) or not segmentation:
        return None
    polygon = segmentation[0]
    if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2 != 0:
        return None
    try:
        values = [float(value) for value in polygon]
    except (TypeError, ValueError):
        return None
    points = [(values[i], values[i + 1]) for i in range(0, len(values), 2)]
    if any(not math.isfinite(x) or not math.isfinite(y) for x, y in points):
        return None
    return points


def order_quad(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    ordered = pts[np.argsort(angles)]
    start = int(np.argmin(ordered.sum(axis=1)))
    return np.roll(ordered, -start, axis=0)


def min_area_quad(points: list[tuple[float, float]], width: int, height: int) -> np.ndarray | None:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if pts.shape[0] < 3:
        return None
    rect = cv2.minAreaRect(pts)
    quad = cv2.boxPoints(rect).astype(np.float32)
    quad[:, 0] = np.clip(quad[:, 0], 0.0, float(max(0, width - 1)))
    quad[:, 1] = np.clip(quad[:, 1], 0.0, float(max(0, height - 1)))
    return order_quad(quad)


def quad_area(quad: np.ndarray) -> float:
    return float(abs(cv2.contourArea(np.asarray(quad, dtype=np.float32).reshape(-1, 2))))


def format_obb_line(quad: np.ndarray, width: int, height: int) -> str:
    values: list[str] = ["0"]
    for x, y in order_quad(quad):
        values.append(f"{float(np.clip(x / width, 0.0, 1.0)):.8f}")
        values.append(f"{float(np.clip(y / height, 0.0, 1.0)):.8f}")
    return " ".join(values)


def safe_stem(text: str) -> str:
    cleaned = []
    for char in text:
        cleaned.append(char if char.isalnum() or char in ("-", "_") else "_")
    value = "".join(cleaned).strip("_")
    while "__" in value:
        value = value.replace("__", "_")
    return value or "image"


def place_image(src: Path, dst: Path, mode: str) -> None:
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


def load_records(args: argparse.Namespace, root: Path) -> tuple[list[ImageRecord], dict[str, Any]]:
    coco_paths = iter_coco_jsons(root)
    if not coco_paths:
        raise FileNotFoundError(f"No COCO annotations JSON found under {root}")
    image_index = build_image_index(root)
    records: dict[str, ImageRecord] = {}
    dropped: list[dict[str, Any]] = []
    counters = {
        "coco_files": len(coco_paths),
        "coco_images": 0,
        "coco_annotations": 0,
        "dropped_non_chip": 0,
        "dropped_missing_image": 0,
        "dropped_invalid_segmentation": 0,
        "dropped_non_quad": 0,
        "dropped_tiny_area": 0,
    }

    for coco_path in coco_paths:
        coco = json.loads(coco_path.read_text(encoding="utf-8"))
        mapping = category_mapping(coco)
        image_by_id: dict[int, dict[str, Any]] = {}
        for image_info in coco.get("images", []):
            counters["coco_images"] += 1
            image_id = int(image_info["id"])
            file_name = str(image_info.get("file_name", ""))
            image_path = resolve_image_path(root, image_index, file_name)
            if image_path is None:
                counters["dropped_missing_image"] += 1
                continue
            key = image_path.resolve().as_posix()
            if key not in records:
                image = read_image(image_path)
                height, width = image.shape[:2]
                records[key] = ImageRecord(
                    image_id=image_id,
                    file_name=file_name,
                    image_path=image_path,
                    width=int(image_info.get("width") or width),
                    height=int(image_info.get("height") or height),
                )
            image_by_id[image_id] = {"record": records[key], "file_name": file_name}

        for ann in coco.get("annotations", []):
            counters["coco_annotations"] += 1
            cat_id = int(ann.get("category_id", -1))
            if cat_id not in mapping:
                counters["dropped_non_chip"] += 1
                continue
            image_id = int(ann.get("image_id", -1))
            target = image_by_id.get(image_id)
            if target is None:
                counters["dropped_missing_image"] += 1
                continue
            points = parse_polygon(ann.get("segmentation"))
            if points is None:
                counters["dropped_invalid_segmentation"] += 1
                dropped.append({"reason": "invalid_segmentation", "annotation_id": ann.get("id"), "image_id": image_id})
                continue
            if args.drop_non_quad and len(points) != 4:
                counters["dropped_non_quad"] += 1
                dropped.append(
                    {
                        "reason": "non_quad_polygon",
                        "annotation_id": ann.get("id"),
                        "image_id": image_id,
                        "file_name": target["file_name"],
                        "points": len(points),
                    }
                )
                continue
            record: ImageRecord = target["record"]
            quad = min_area_quad(points, record.width, record.height)
            if quad is None or quad_area(quad) < args.min_area:
                counters["dropped_tiny_area"] += 1
                dropped.append({"reason": "tiny_area", "annotation_id": ann.get("id"), "image_id": image_id})
                continue
            record.objects.append(ObjectRecord(points=[(float(x), float(y)) for x, y in quad], annotation_id=ann.get("id")))

    report = {"counters": counters, "dropped_annotations": dropped}
    return list(records.values()), report


def split_records(records: list[ImageRecord], args: argparse.Namespace) -> dict[str, list[ImageRecord]]:
    ratios = [args.train_ratio, args.valid_ratio, args.test_ratio]
    if any(value < 0 for value in ratios) or sum(ratios) <= 0:
        raise ValueError("split ratios must be non-negative and sum to a positive value")
    total = sum(ratios)
    train_cut = ratios[0] / total
    valid_cut = (ratios[0] + ratios[1]) / total
    rng = random.Random(args.seed)
    shuffled = list(records)
    shuffled.sort(key=lambda r: r.image_path.name)
    rng.shuffle(shuffled)
    splits = {split: [] for split in SPLITS}
    for record in shuffled:
        value = rng.random()
        if value < train_cut:
            splits["train"].append(record)
        elif value < valid_cut:
            splits["valid"].append(record)
        else:
            splits["test"].append(record)
    return splits


def write_dataset(records: list[ImageRecord], report: dict[str, Any], args: argparse.Namespace) -> None:
    output_dir = args.output_dir.resolve()
    ensure_clean_output(output_dir, args.overwrite)
    splits = split_records(records, args)
    used_names: set[str] = set()
    split_stats: dict[str, dict[str, int]] = {}
    all_output_images: list[Path] = []

    for split, split_records_list in splits.items():
        images_dir = output_dir / split / "images"
        labels_dir = output_dir / split / "labels"
        images_dir.mkdir(parents=True, exist_ok=True)
        labels_dir.mkdir(parents=True, exist_ok=True)
        object_count = 0
        empty_count = 0
        for record in split_records_list:
            stem = safe_stem(Path(record.file_name).stem or record.image_path.stem)
            output_name = f"{stem}{record.image_path.suffix.lower() if record.image_path.suffix else '.jpg'}"
            if output_name.lower() in used_names:
                output_name = f"{stem}_{abs(hash(record.image_path.resolve().as_posix())) & 0xFFFFFFFF:08x}.jpg"
            used_names.add(output_name.lower())
            dst_image = images_dir / output_name
            if record.image_path.suffix.lower() in {".jpg", ".jpeg"}:
                place_image(record.image_path, dst_image, args.image_mode)
            else:
                write_jpeg(dst_image, read_image(record.image_path))
            lines = [
                format_obb_line(np.asarray(obj.points, dtype=np.float32), record.width, record.height)
                for obj in record.objects
            ]
            object_count += len(lines)
            if not lines:
                empty_count += 1
            (labels_dir / f"{dst_image.stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            all_output_images.append(dst_image)
        split_stats[split] = {
            "images": len(split_records_list),
            "objects": object_count,
            "empty_label_files": empty_count,
        }

    data_yaml = output_dir / "data.yaml"
    data_yaml.write_text(
        "\n".join(
            [
                f"path: {output_dir.as_posix()}",
                "train: train/images",
                "val: valid/images",
                "test: test/images",
                "names:",
                "  0: chip",
                "",
            ]
        ),
        encoding="utf-8",
    )

    rng = random.Random(args.seed)
    calib_images = list(all_output_images)
    rng.shuffle(calib_images)
    calib_images = calib_images[: max(0, min(args.calib_count, len(calib_images)))]
    if args.calib_output:
        args.calib_output.parent.mkdir(parents=True, exist_ok=True)
        args.calib_output.write_text("\n".join(str(path.resolve()) for path in calib_images) + "\n", encoding="utf-8")
    if args.labels_output:
        args.labels_output.parent.mkdir(parents=True, exist_ok=True)
        args.labels_output.write_text("chip\n", encoding="utf-8")

    dataset_report = {
        "source": str(args.input.resolve()),
        "output": str(output_dir),
        "class_names": CLASS_NAMES,
        "splits": split_stats,
        "total_images": len(records),
        "total_objects": sum(len(record.objects) for record in records),
        "total_empty_label_files": sum(1 for record in records if not record.objects),
        "calib_count": len(calib_images),
        **report,
    }
    (output_dir / "dataset_report.json").write_text(
        json.dumps(dataset_report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def self_check(output_dir: Path) -> None:
    for split in SPLITS:
        labels_dir = output_dir / split / "labels"
        for label_path in labels_dir.glob("*.txt"):
            for line_no, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) != 9:
                    raise RuntimeError(f"{label_path}:{line_no}: expected 9 YOLO OBB columns, got {len(parts)}")
                coords = [float(value) for value in parts[1:]]
                if any(value < 0.0 or value > 1.0 for value in coords):
                    raise RuntimeError(f"{label_path}:{line_no}: coordinate outside [0,1]")


def main() -> None:
    args = parse_args()
    root, temp_dir = extract_input(args.input)
    try:
        records, report = load_records(args, root)
        if not records:
            raise RuntimeError(f"No images found in CVAT export: {args.input}")
        write_dataset(records, report, args)
        self_check(args.output_dir.resolve())
        dataset_report = json.loads((args.output_dir.resolve() / "dataset_report.json").read_text(encoding="utf-8"))
        print(
            f"prepared {args.output_dir}: images={dataset_report['total_images']} "
            f"objects={dataset_report['total_objects']} empty={dataset_report['total_empty_label_files']} "
            f"dropped_non_quad={dataset_report['counters']['dropped_non_quad']}"
        )
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Prepare chip-class oriented-box CVAT task packages.

The task packages are meant for manual correction of the chip locator, not for
defect segmentation. Initial labels are single-class chip quadrilaterals built
from existing HBB labels or capture metadata crop boxes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cloud_training.chip_roi_yolov8_rknn.scripts.prepare_obb_dataset import (  # noqa: E402
    estimate_obb,
    format_obb_line,
    horizontal_quad,
    yolo_hbb_to_pixels,
)
from tools.seg_cvat_pipeline import polygon_area, read_image, write_jpeg  # noqa: E402


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
CVAT_COCO_SUBSET = "default"
CLASS_NAME = "chip"


@dataclass
class ChipObject:
    quad: np.ndarray
    source: str


@dataclass
class Sample:
    source_kind: str
    source_id: str
    image_path: Path
    objects: list[ChipObject] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    duplicate_sources: list[str] = field(default_factory=list)
    sha1: str = ""
    width: int = 0
    height: int = 0

    @property
    def object_count(self) -> int:
        return len(self.objects)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("chip_roi/cvat_obb_tasks_20260509"))
    parser.add_argument("--chunk-size", type=int, default=150)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--zip", action="store_true", help="Write one CVAT-ready zip per part.")
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--dedupe", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-chip-roi", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-seg-full", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-gui-capture", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--preview-count", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--image-mode",
        choices=("copy", "hardlink"),
        default="copy",
        help="Use copy for self-contained task folders; hardlink saves disk before zipping.",
    )
    parser.add_argument(
        "--chip-roi-dataset",
        type=Path,
        default=Path("chip_roi/generated/cloud_chip_roi_yolo"),
        help="YOLO HBB chip ROI dataset root with train/valid/test images and labels.",
    )
    parser.add_argument(
        "--gui-capture-dir",
        type=Path,
        default=Path("chip_roi/generated/gui_capture"),
        help="GUI chip ROI capture directory with images and labels.",
    )
    parser.add_argument(
        "--seg-captures-dir",
        type=Path,
        default=Path("chip_seg/captures"),
        help="Segmentation capture root; uses session/images_full plus session/meta crop_box.",
    )
    return parser.parse_args()


def ensure_clean_dir(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"Output already exists: {path}. Use --overwrite to replace it.")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def iter_images(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def safe_name(text: str) -> str:
    cleaned = []
    for char in text:
        if char.isalnum() or char in ("-", "_"):
            cleaned.append(char)
        else:
            cleaned.append("_")
    value = "".join(cleaned).strip("_")
    while "__" in value:
        value = value.replace("__", "_")
    return value or "sample"


def image_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def link_or_copy(src: Path, dst: Path, mode: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "hardlink":
        try:
            os.link(src, dst)
            return
        except OSError:
            pass
    shutil.copy2(src, dst)


def parse_yolo_hbb_label(label_path: Path, image: np.ndarray, source: str) -> list[ChipObject]:
    if not label_path.exists():
        return []
    height, width = image.shape[:2]
    objects: list[ChipObject] = []
    for line_no, raw in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        parts = raw.split()
        if not parts:
            continue
        if len(parts) != 5:
            continue
        try:
            cls_id = int(float(parts[0]))
            cx, cy, box_w, box_h = [float(value) for value in parts[1:]]
        except ValueError:
            continue
        if cls_id != 0 or box_w <= 0.0 or box_h <= 0.0:
            continue
        try:
            hbb = yolo_hbb_to_pixels(cx, cy, box_w, box_h, width, height)
            quad, method = estimate_obb(image, hbb, padding_ratio=0.18, min_contour_area_ratio=0.18)
        except Exception:
            x1 = cx * width - box_w * width / 2.0
            y1 = cy * height - box_h * height / 2.0
            x2 = cx * width + box_w * width / 2.0
            y2 = cy * height + box_h * height / 2.0
            quad = horizontal_quad(x1, y1, x2, y2)
            method = "fallback_exception"
        objects.append(ChipObject(quad=quad, source=f"{source}:{label_path.name}:{line_no}:{method}"))
    return objects


def read_capture_crop_box(meta_path: Path) -> tuple[list[float] | None, list[list[float]] | None, dict[str, Any]]:
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None, None, {}
    crop_box = data.get("crop_box")
    if isinstance(crop_box, list) and len(crop_box) == 4:
        try:
            crop = [float(value) for value in crop_box]
        except (TypeError, ValueError):
            crop = None
    else:
        crop = None
    obb_points = data.get("crop_obb_points")
    if isinstance(obb_points, list) and len(obb_points) == 4:
        try:
            points = [[float(point[0]), float(point[1])] for point in obb_points]
        except (TypeError, ValueError, IndexError):
            points = None
    else:
        points = None
    return crop, points, data


def objects_from_crop_meta(image: np.ndarray, meta_path: Path, source: str) -> tuple[list[ChipObject], list[str]]:
    height, width = image.shape[:2]
    crop_box, obb_points, data = read_capture_crop_box(meta_path)
    notes: list[str] = []
    if obb_points:
        quad = np.asarray(obb_points, dtype=np.float32).reshape(4, 2)
        return [ChipObject(quad=quad, source=f"{source}:{meta_path.name}:crop_obb_points")], notes
    if not crop_box:
        notes.append("missing_crop_box")
        return [], notes
    x1, y1, x2, y2 = crop_box
    x1 = max(0.0, min(float(width - 1), x1))
    y1 = max(0.0, min(float(height - 1), y1))
    x2 = max(0.0, min(float(width - 1), x2))
    y2 = max(0.0, min(float(height - 1), y2))
    if x2 <= x1 + 2.0 or y2 <= y1 + 2.0:
        notes.append("invalid_crop_box")
        return [], notes
    try:
        quad, method = estimate_obb(image, (x1, y1, x2, y2), padding_ratio=0.08, min_contour_area_ratio=0.18)
    except Exception:
        quad = horizontal_quad(x1, y1, x2, y2)
        method = "fallback_exception"
    if not data:
        notes.append("meta_parse_empty")
    return [ChipObject(quad=quad, source=f"{source}:{meta_path.name}:{method}")], notes


def collect_chip_roi_dataset(root: Path) -> list[Sample]:
    samples: list[Sample] = []
    for split in ("train", "valid", "test"):
        images_dir = root / split / "images"
        labels_dir = root / split / "labels"
        for image_path in iter_images(images_dir):
            try:
                image = read_image(image_path)
            except Exception as exc:
                samples.append(
                    Sample(
                        source_kind="chip_roi_yolo",
                        source_id=f"{split}/{image_path.name}",
                        image_path=image_path,
                        notes=[f"read_failed:{exc}"],
                    )
                )
                continue
            label_path = labels_dir / f"{image_path.stem}.txt"
            objects = parse_yolo_hbb_label(label_path, image, f"chip_roi_yolo/{split}")
            samples.append(
                Sample(
                    source_kind="chip_roi_yolo",
                    source_id=f"{split}/{image_path.name}",
                    image_path=image_path,
                    objects=objects,
                    width=image.shape[1],
                    height=image.shape[0],
                    notes=[] if objects else ["no_initial_chip_label"],
                )
            )
    return samples


def collect_gui_capture(root: Path) -> list[Sample]:
    samples: list[Sample] = []
    images_dir = root / "images"
    labels_dir = root / "labels"
    for image_path in iter_images(images_dir):
        try:
            image = read_image(image_path)
        except Exception as exc:
            samples.append(
                Sample(
                    source_kind="chip_roi_gui_capture",
                    source_id=image_path.name,
                    image_path=image_path,
                    notes=[f"read_failed:{exc}"],
                )
            )
            continue
        label_path = labels_dir / f"{image_path.stem}.txt"
        objects = parse_yolo_hbb_label(label_path, image, "chip_roi_gui_capture")
        samples.append(
            Sample(
                source_kind="chip_roi_gui_capture",
                source_id=image_path.name,
                image_path=image_path,
                objects=objects,
                width=image.shape[1],
                height=image.shape[0],
                notes=[] if objects else ["no_initial_chip_label"],
            )
        )
    return samples


def collect_seg_full_captures(root: Path) -> list[Sample]:
    samples: list[Sample] = []
    if not root.exists():
        return samples
    for session in sorted(p for p in root.iterdir() if p.is_dir()):
        full_dir = session / "images_full"
        meta_dir = session / "meta"
        if not full_dir.exists() or not meta_dir.exists():
            continue
        for image_path in iter_images(full_dir):
            meta_path = meta_dir / f"{image_path.stem}.json"
            try:
                image = read_image(image_path)
            except Exception as exc:
                samples.append(
                    Sample(
                        source_kind="seg_capture_full",
                        source_id=f"{session.name}/{image_path.name}",
                        image_path=image_path,
                        notes=[f"read_failed:{exc}"],
                    )
                )
                continue
            objects, notes = objects_from_crop_meta(image, meta_path, f"seg_capture_full/{session.name}")
            samples.append(
                Sample(
                    source_kind="seg_capture_full",
                    source_id=f"{session.name}/{image_path.name}",
                    image_path=image_path,
                    objects=objects,
                    width=image.shape[1],
                    height=image.shape[0],
                    notes=notes if notes else ([] if objects else ["no_initial_chip_label"]),
                )
            )
    return samples


def source_rank(sample: Sample) -> tuple[int, int]:
    priority = {
        "seg_capture_full": 0,
        "chip_roi_yolo": 1,
        "chip_roi_gui_capture": 2,
    }.get(sample.source_kind, 9)
    return (-sample.object_count, priority)


def dedupe_samples(samples: list[Sample]) -> tuple[list[Sample], int]:
    by_hash: dict[str, list[Sample]] = {}
    for sample in samples:
        if not sample.image_path.exists() or sample.width <= 0 or sample.height <= 0:
            continue
        sample.sha1 = image_sha1(sample.image_path)
        by_hash.setdefault(sample.sha1, []).append(sample)

    unique: list[Sample] = []
    duplicate_count = 0
    for group in by_hash.values():
        group.sort(key=source_rank)
        chosen = group[0]
        for duplicate in group[1:]:
            duplicate_count += 1
            chosen.duplicate_sources.append(f"{duplicate.source_kind}:{duplicate.source_id}")
            if not chosen.objects and duplicate.objects:
                chosen.objects = duplicate.objects
                chosen.notes.append(f"label_taken_from_duplicate:{duplicate.source_kind}:{duplicate.source_id}")
        unique.append(chosen)
    unique.sort(key=lambda item: (item.source_kind, item.source_id))
    return unique, duplicate_count


def sample_output_name(sample: Sample, used: set[str]) -> str:
    suffix = ".jpg"
    base = safe_name(f"{sample.source_kind}_{sample.source_id}_{sample.sha1[:8]}")
    name = base + suffix
    counter = 2
    while name.lower() in used:
        name = f"{base}_{counter}{suffix}"
        counter += 1
    used.add(name.lower())
    return name


def quad_to_points(quad: np.ndarray, width: int, height: int) -> list[tuple[float, float]]:
    pts = np.asarray(quad, dtype=np.float32).reshape(4, 2).copy()
    pts[:, 0] = np.clip(pts[:, 0], 0.0, float(max(0, width - 1)))
    pts[:, 1] = np.clip(pts[:, 1], 0.0, float(max(0, height - 1)))
    return [(float(x), float(y)) for x, y in pts]


def bbox_from_points(points: list[tuple[float, float]]) -> list[float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    return [x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1)]


def write_coco(path: Path, rows: list[dict[str, Any]]) -> int:
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    ann_id = 1
    for image_id, row in enumerate(rows, start=1):
        images.append(
            {
                "id": image_id,
                "file_name": f"{CVAT_COCO_SUBSET}/{row['output_name']}",
                "width": row["width"],
                "height": row["height"],
            }
        )
        for obj in row["objects"]:
            points = obj["points"]
            if len(points) < 3:
                continue
            segmentation = [coord for point in points for coord in point]
            annotations.append(
                {
                    "id": ann_id,
                    "image_id": image_id,
                    "category_id": 1,
                    "segmentation": [segmentation],
                    "area": polygon_area(points),
                    "bbox": bbox_from_points(points),
                    "iscrowd": 0,
                }
            )
            ann_id += 1
    data = {
        "images": images,
        "annotations": annotations,
        "categories": [{"id": 1, "name": CLASS_NAME, "supercategory": "chip"}],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(annotations)


def write_cvat_xml(path: Path, rows: list[dict[str, Any]]) -> int:
    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"
    meta = ET.SubElement(root, "meta")
    task = ET.SubElement(meta, "task")
    ET.SubElement(task, "name").text = "chip_obb_manual"
    labels = ET.SubElement(task, "labels")
    label = ET.SubElement(labels, "label")
    ET.SubElement(label, "name").text = CLASS_NAME
    ET.SubElement(label, "color").text = "#ffcc33"
    ET.SubElement(label, "type").text = "polygon"
    ET.SubElement(label, "attributes")

    shape_count = 0
    for image_id, row in enumerate(rows):
        image = ET.SubElement(
            root,
            "image",
            {
                "id": str(image_id),
                "name": f"{CVAT_COCO_SUBSET}/{row['output_name']}",
                "width": str(row["width"]),
                "height": str(row["height"]),
            },
        )
        for obj in row["objects"]:
            points = obj["points"]
            if len(points) < 3:
                continue
            points_text = ";".join(f"{x:.2f},{y:.2f}" for x, y in points)
            ET.SubElement(
                image,
                "polygon",
                {
                    "label": CLASS_NAME,
                    "source": "auto",
                    "occluded": "0",
                    "points": points_text,
                    "z_order": "0",
                },
            )
            shape_count += 1
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return shape_count


def draw_preview(image: np.ndarray, objects: list[dict[str, Any]]) -> np.ndarray:
    preview = image.copy()
    for obj in objects:
        points = obj["points"]
        if len(points) < 2:
            continue
        pts = np.asarray([[int(round(x)), int(round(y))] for x, y in points], dtype=np.int32)
        cv2.polylines(preview, [pts], isClosed=True, color=(0, 220, 255), thickness=2, lineType=cv2.LINE_AA)
        cv2.putText(
            preview,
            CLASS_NAME,
            tuple(pts[0]),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 220, 255),
            2,
            cv2.LINE_AA,
        )
    return preview


def write_part_readme(path: Path, part_name: str, image_count: int, ann_count: int) -> None:
    path.write_text(
        "\n".join(
            [
                f"# {part_name}",
                "",
                f"- Images: {image_count}",
                f"- Initial chip annotations: {ann_count}",
                "- Label: chip",
                "- Annotation shape: 4-point polygon for oriented chip correction.",
                "",
                "CVAT usage:",
                "1. Create one Task for this part zip.",
                "2. If CVAT does not auto-load annotations from the zip, import `annotations/instances_default.json` as COCO 1.0 or `annotations.xml` as CVAT for images.",
                "3. Correct the chip outline only; add a chip polygon if missing, delete it if the frame is unusable or has no complete chip.",
                "4. Keep exactly one polygon for a normal single-chip frame unless the image truly contains multiple complete chips.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def package_part(part_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(part_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(part_dir))


def write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "output_name",
        "source_kind",
        "source_id",
        "source_path",
        "sha1",
        "width",
        "height",
        "initial_chip_annotations",
        "notes",
        "duplicate_sources",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "output_name": row["output_name"],
                    "source_kind": row["sample"].source_kind,
                    "source_id": row["sample"].source_id,
                    "source_path": str(row["sample"].image_path),
                    "sha1": row["sample"].sha1,
                    "width": row["width"],
                    "height": row["height"],
                    "initial_chip_annotations": len(row["objects"]),
                    "notes": ";".join(row["sample"].notes),
                    "duplicate_sources": ";".join(row["sample"].duplicate_sources),
                }
            )


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def write_top_readme(path: Path, summary: dict[str, Any]) -> None:
    path.write_text(
        "\n".join(
            [
                "# Chip OBB CVAT Tasks",
                "",
                "Purpose: manually correct the single `chip` class for an oriented chip locator.",
                "",
                "## Contents",
                "",
                "- `part_001.zip` onward: CVAT task packages.",
                "- `part_*/images/default/*.jpg`: images for annotation.",
                "- `part_*/annotations/instances_default.json`: COCO polygon prelabels.",
                "- `part_*/annotations.xml`: CVAT for images polygon prelabels.",
                "- `part_*/labels/*.txt`: YOLO OBB 9-column prelabels for local checks.",
                "- `part_*/manifest.csv`: source traceability and duplicate source notes.",
                "- `summary.json`: source counts and package summary.",
                "- `previews/*.jpg`: quick visual checks of initial chip polygons.",
                "",
                "## CVAT Usage",
                "",
                "1. Create one CVAT Task per `part_*.zip`.",
                "2. Label set should contain only one label: `chip`.",
                "3. If annotations are not loaded automatically, import either:",
                "   - `annotations/instances_default.json` as `COCO 1.0`, or",
                "   - `annotations.xml` as `CVAT for images`.",
                "4. Correct only the chip outline. Add a `chip` polygon if missing; delete it if the image is unusable or truly has no complete chip.",
                "5. Keep one `chip` polygon for normal single-chip images. Use multiple polygons only when the image truly contains multiple complete chips.",
                "",
                "## Export",
                "",
                "After annotation, export each task as `COCO 1.0`. Keep images enabled only if the exported package needs to be self-contained; for local merge, annotations alone are usually enough because source images are already present in this folder.",
                "",
                "## Build Summary",
                "",
                f"- Collected source samples: {summary['collected_samples']}",
                f"- Unique images after SHA1 dedupe: {summary['unique_samples']}",
                f"- Duplicate images removed: {summary['duplicates_removed']}",
                f"- Initial chip annotations: {summary['total_initial_chip_annotations']}",
                f"- Parts: {len(summary['parts'])}",
                "",
                "ROI-crop defect segmentation images were not separately packaged when their full-frame `images_full` source was available.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build_tasks(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    ensure_clean_dir(output_dir, args.overwrite)

    collected: list[Sample] = []
    source_counts: dict[str, int] = {}
    if args.include_chip_roi:
        samples = collect_chip_roi_dataset(args.chip_roi_dataset)
        source_counts["chip_roi_yolo"] = len(samples)
        collected.extend(samples)
    if args.include_gui_capture:
        samples = collect_gui_capture(args.gui_capture_dir)
        source_counts["chip_roi_gui_capture"] = len(samples)
        collected.extend(samples)
    if args.include_seg_full:
        samples = collect_seg_full_captures(args.seg_captures_dir)
        source_counts["seg_capture_full"] = len(samples)
        collected.extend(samples)

    readable = [sample for sample in collected if sample.width > 0 and sample.height > 0 and sample.image_path.exists()]
    if args.dedupe:
        samples, duplicate_count = dedupe_samples(readable)
    else:
        samples = readable
        for sample in samples:
            sample.sha1 = image_sha1(sample.image_path)
        duplicate_count = 0

    used_names: set[str] = set()
    chunk_size = max(1, int(args.chunk_size))
    part_summaries: list[dict[str, Any]] = []
    total_annotations = 0
    preview_written = 0
    preview_dir = output_dir / "previews"

    for part_index, start in enumerate(range(0, len(samples), chunk_size), start=1):
        part_samples = samples[start : start + chunk_size]
        part_name = f"part_{part_index:03d}"
        part_dir = output_dir / part_name
        images_dir = part_dir / "images" / CVAT_COCO_SUBSET
        labels_dir = part_dir / "labels"
        annotations_dir = part_dir / "annotations"
        for directory in (images_dir, labels_dir, annotations_dir):
            directory.mkdir(parents=True, exist_ok=True)

        rows: list[dict[str, Any]] = []
        for sample in part_samples:
            output_name = sample_output_name(sample, used_names)
            dst_image = images_dir / output_name
            if sample.image_path.suffix.lower() in {".jpg", ".jpeg"}:
                link_or_copy(sample.image_path, dst_image, args.image_mode)
            else:
                image = read_image(sample.image_path)
                write_jpeg(dst_image, image, quality=args.jpeg_quality)
            image = read_image(dst_image)
            height, width = image.shape[:2]
            objects: list[dict[str, Any]] = []
            yolo_lines: list[str] = []
            for obj in sample.objects:
                points = quad_to_points(obj.quad, width, height)
                if polygon_area(points) < 4.0:
                    continue
                objects.append({"points": points, "source": obj.source})
                yolo_lines.append(format_obb_line(0, np.asarray(points, dtype=np.float32), width, height))
            (labels_dir / f"{Path(output_name).stem}.txt").write_text(
                "\n".join(yolo_lines) + ("\n" if yolo_lines else ""),
                encoding="utf-8",
            )
            rows.append(
                {
                    "sample": sample,
                    "output_name": output_name,
                    "width": width,
                    "height": height,
                    "objects": objects,
                }
            )
            if preview_written < args.preview_count:
                preview = draw_preview(image, objects)
                write_jpeg(preview_dir / f"{part_name}_{Path(output_name).stem}.jpg", preview, quality=92)
                preview_written += 1

        coco_annotations = write_coco(annotations_dir / "instances_default.json", rows)
        xml_annotations = write_cvat_xml(part_dir / "annotations.xml", rows)
        if coco_annotations != xml_annotations:
            raise RuntimeError(f"{part_name}: COCO/XML annotation mismatch: {coco_annotations} vs {xml_annotations}")
        total_annotations += coco_annotations
        (part_dir / "labels.txt").write_text(f"{CLASS_NAME}\n", encoding="utf-8")
        write_manifest(part_dir / "manifest.csv", rows)
        write_part_readme(part_dir / "README.md", part_name, len(rows), coco_annotations)
        if args.zip:
            package_part(part_dir, output_dir / f"{part_name}.zip")
        part_summaries.append(
            {
                "part": part_name,
                "images": len(rows),
                "initial_chip_annotations": coco_annotations,
                "zip": str(output_dir / f"{part_name}.zip") if args.zip else "",
            }
        )
        print(f"wrote {part_name}: images={len(rows)} annotations={coco_annotations}")

    summary = {
        "output_dir": str(output_dir),
        "chunk_size": chunk_size,
        "source_counts": source_counts,
        "collected_samples": len(collected),
        "readable_samples": len(readable),
        "unique_samples": len(samples),
        "duplicates_removed": duplicate_count,
        "total_initial_chip_annotations": total_annotations,
        "parts": part_summaries,
        "notes": [
            "ROI-crop defect segmentation images are not separately packaged when their full-frame images_full source is available.",
            "Initial annotations are four-point chip polygons suitable for manual OBB correction and YOLO OBB conversion.",
        ],
    }
    write_summary(output_dir / "summary.json", summary)
    write_top_readme(output_dir / "README.md", summary)
    return summary


def main() -> int:
    args = parse_args()
    summary = build_tasks(args)
    print(
        f"complete: unique_images={summary['unique_samples']} "
        f"annotations={summary['total_initial_chip_annotations']} "
        f"parts={len(summary['parts'])} output={summary['output_dir']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

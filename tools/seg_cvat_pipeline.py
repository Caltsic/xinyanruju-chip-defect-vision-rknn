#!/usr/bin/env python3
"""Capture, package, and merge chip defect segmentation data for CVAT.

The tool keeps the project-specific choices in one place:

- capture IMX678 two-stage segmentation frames as chip ROI crops;
- save current board segmentation contours as editable prelabels;
- split captures into CVAT-friendly tasks with COCO instance annotations;
- merge CVAT COCO exports back into a YOLOv8 segmentation raw dataset.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shutil
import sys
import tempfile
import time
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.adb_imx415_rknn_live_view import (
    CHIP_DEFECT_SEG_REMOTE_MODEL,
    DEFAULT_SERIAL,
    Detection,
    detection_points,
    default_adb_path,
    normalize_points,
)
from tools.chip_roi_utils import clamp_box, expand_box
from tools.chip_capture_gui.camera import create_camera, format_stream_error, write_input_adjust_config
from tools.chip_capture_gui.settings import CameraSettings, ImageAdjustSettings, LightSettings
from tools.chip_capture_gui.ws2812 import create_ws2812_controller


CLASS_NAMES = ["ZF-scratch", "scratch", "broken", "pinbreak"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
SPLITS = ("train", "valid", "test")
CVAT_COCO_SUBSET = "default"


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


def polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    last_x, last_y = points[-1]
    for x, y in points:
        area += last_x * y - x * last_y
        last_x, last_y = x, y
    return abs(area) * 0.5


def bbox_from_points(points: list[tuple[float, float]]) -> list[float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    return [x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1)]


def yolo_line_to_polygon(line: str, width: int, height: int) -> tuple[int, list[tuple[float, float]]] | None:
    parts = line.strip().split()
    if len(parts) < 7 or len(parts) % 2 != 1:
        return None
    cls_id = int(float(parts[0]))
    values = [float(value) for value in parts[1:]]
    points = [
        (
            max(0.0, min(float(width - 1), values[i] * width)),
            max(0.0, min(float(height - 1), values[i + 1] * height)),
        )
        for i in range(0, len(values), 2)
    ]
    if len(points) < 3:
        return None
    return cls_id, points


def polygon_to_yolo_line(cls_id: int, points: list[tuple[float, float]], width: int, height: int) -> str | None:
    if len(points) < 3 or width <= 0 or height <= 0:
        return None
    unique: list[tuple[float, float]] = []
    for x, y in points:
        clipped = (
            max(0.0, min(float(width - 1), float(x))),
            max(0.0, min(float(height - 1), float(y))),
        )
        if not unique or math.hypot(unique[-1][0] - clipped[0], unique[-1][1] - clipped[1]) >= 1.0:
            unique.append(clipped)
    if len(unique) > 1 and math.hypot(unique[0][0] - unique[-1][0], unique[0][1] - unique[-1][1]) < 1.0:
        unique.pop()
    if len(unique) < 3 or polygon_area(unique) < 2.0:
        return None
    values: list[str] = [str(cls_id)]
    for x, y in unique:
        values.append(f"{x / width:.8f}")
        values.append(f"{y / height:.8f}")
    return " ".join(values)


def parse_rgb(text: str) -> tuple[int, int, int]:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("RGB must be R,G,B")
    try:
        channels = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("RGB channels must be integers") from exc
    if any(channel < 0 or channel > 255 for channel in channels):
        raise argparse.ArgumentTypeError("RGB channels must be in 0..255")
    return channels  # type: ignore[return-value]


def clip_polygon_axis(
    points: list[tuple[float, float]],
    inside,
    intersect,
) -> list[tuple[float, float]]:
    if not points:
        return []
    clipped: list[tuple[float, float]] = []
    previous = points[-1]
    previous_inside = inside(previous)
    for current in points:
        current_inside = inside(current)
        if current_inside:
            if not previous_inside:
                clipped.append(intersect(previous, current))
            clipped.append(current)
        elif previous_inside:
            clipped.append(intersect(previous, current))
        previous = current
        previous_inside = current_inside
    return clipped


def clip_polygon_to_rect(
    points: list[tuple[float, float]],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> list[tuple[float, float]]:
    def intersect_x(boundary: float):
        def _intersect(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
            dx = b[0] - a[0]
            if abs(dx) < 1e-9:
                return boundary, a[1]
            t = (boundary - a[0]) / dx
            return boundary, a[1] + (b[1] - a[1]) * t

        return _intersect

    def intersect_y(boundary: float):
        def _intersect(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
            dy = b[1] - a[1]
            if abs(dy) < 1e-9:
                return a[0], boundary
            t = (boundary - a[1]) / dy
            return a[0] + (b[0] - a[0]) * t, boundary

        return _intersect

    clipped = list(points)
    clipped = clip_polygon_axis(clipped, lambda p: p[0] >= x1, intersect_x(x1))
    clipped = clip_polygon_axis(clipped, lambda p: p[0] <= x2, intersect_x(x2))
    clipped = clip_polygon_axis(clipped, lambda p: p[1] >= y1, intersect_y(y1))
    clipped = clip_polygon_axis(clipped, lambda p: p[1] <= y2, intersect_y(y2))
    return clipped


def session_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_capture_path(input_dir: Path, raw_value: str | None, fallback_dir: str, fallback_name: str) -> Path:
    candidates: list[Path] = []
    if raw_value:
        raw_path = Path(raw_value)
        candidates.append(raw_path)
        if not raw_path.is_absolute():
            candidates.append(input_dir / raw_path)
        candidates.append(input_dir / fallback_dir / raw_path.name)
    candidates.append(input_dir / fallback_dir / fallback_name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def decode_compressed_coco_counts(counts: str | bytes) -> list[int]:
    text = counts.decode("ascii") if isinstance(counts, bytes) else counts
    decoded: list[int] = []
    index = 0
    while index < len(text):
        value = 0
        shift = 0
        more = True
        while more:
            raw = ord(text[index]) - 48
            index += 1
            value |= (raw & 0x1F) << shift
            more = bool(raw & 0x20)
            shift += 5
            if not more and (raw & 0x10):
                value |= -1 << shift
        if len(decoded) > 2:
            value += decoded[-2]
        decoded.append(int(value))
    return decoded


def decode_coco_rle(segmentation: dict[str, Any], width: int, height: int) -> np.ndarray | None:
    size = segmentation.get("size") or [height, width]
    if len(size) != 2:
        return None
    rle_h, rle_w = int(size[0]), int(size[1])
    counts_raw = segmentation.get("counts")
    if counts_raw is None:
        return None
    try:
        if isinstance(counts_raw, list):
            counts = [int(value) for value in counts_raw]
        else:
            counts = decode_compressed_coco_counts(counts_raw)
    except Exception:
        try:
            from pycocotools import mask as mask_utils  # type: ignore

            decoded = mask_utils.decode({"size": [rle_h, rle_w], "counts": counts_raw})
            return np.ascontiguousarray(decoded.astype(np.uint8))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("failed to decode COCO RLE segmentation; install pycocotools or export polygons") from exc

    flat = np.zeros(rle_h * rle_w, dtype=np.uint8)
    offset = 0
    value = 0
    for count in counts:
        next_offset = min(flat.size, offset + max(0, count))
        if value == 1 and next_offset > offset:
            flat[offset:next_offset] = 1
        offset = next_offset
        value = 1 - value
        if offset >= flat.size:
            break
    if offset == 0:
        return None
    mask = flat.reshape((rle_h, rle_w), order="F")
    if rle_h != height or rle_w != width:
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
    return np.ascontiguousarray(mask)


def mask_to_polygons(mask: np.ndarray, min_area: float = 2.0) -> list[list[tuple[float, float]]]:
    if mask.ndim != 2:
        return []
    binary = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polygons: list[list[tuple[float, float]]] = []
    for contour in contours:
        if contour.shape[0] < 3:
            continue
        epsilon = max(0.75, 0.0025 * cv2.arcLength(contour, True))
        approx = cv2.approxPolyDP(contour, epsilon, True)
        points = [(float(point[0][0]), float(point[0][1])) for point in approx]
        if len(points) >= 3 and polygon_area(points) >= min_area:
            polygons.append(points)
    return polygons


def best_chip_box(detections: list[Detection], width: int, height: int, margin: float) -> tuple[int, int, int, int] | None:
    best: tuple[float, tuple[int, int, int, int]] | None = None
    for detection in detections:
        if detection.class_id != 0:
            continue
        box = clamp_box(
            (
                int(round(detection.x1)),
                int(round(detection.y1)),
                int(round(detection.x2)),
                int(round(detection.y2)),
            ),
            width,
            height,
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        area = float((box[2] - box[0]) * (box[3] - box[1]))
        rank = max(0.001, float(detection.score)) * area
        if best is None or rank > best[0]:
            best = (rank, box)
    if best is None:
        return None
    return expand_box(best[1], width, height, margin, square=False)


def defect_prelabels(
    detections: list[Detection],
    crop_box: tuple[int, int, int, int],
    crop_w: int,
    crop_h: int,
    frame_w: int,
    frame_h: int,
) -> list[str]:
    crop_x1, crop_y1, _crop_x2, _crop_y2 = crop_box
    lines: list[str] = []
    for detection in detections:
        if detection.class_id <= 0:
            continue
        cls_id = detection.class_id - 1
        if cls_id < 0 or cls_id >= len(CLASS_NAMES):
            continue
        points = detection_points(detection)
        if not points:
            continue
        full_points = normalize_points(points, frame_w, frame_h)
        clipped_points = clip_polygon_to_rect(
            full_points,
            float(crop_x1),
            float(crop_y1),
            float(crop_x1 + crop_w - 1),
            float(crop_y1 + crop_h - 1),
        )
        crop_points = [
            (
                max(0.0, min(float(crop_w - 1), x - crop_x1)),
                max(0.0, min(float(crop_h - 1), y - crop_y1)),
            )
            for x, y in clipped_points
        ]
        line = polygon_to_yolo_line(cls_id, crop_points, crop_w, crop_h)
        if line:
            lines.append(line)
    return lines


def draw_prelabel_preview(image: np.ndarray, label_lines: list[str]) -> np.ndarray:
    preview = image.copy()
    overlay = preview.copy()
    height, width = preview.shape[:2]
    colors = [(255, 170, 40), (40, 220, 255), (40, 170, 255), (170, 220, 40)]
    for line in label_lines:
        parsed = yolo_line_to_polygon(line, width, height)
        if parsed is None:
            continue
        cls_id, points = parsed
        pts = np.array([[int(round(x)), int(round(y))] for x, y in points], dtype=np.int32)
        color = colors[cls_id % len(colors)]
        cv2.fillPoly(overlay, [pts], color)
        cv2.polylines(preview, [pts], True, color, 2, cv2.LINE_AA)
    if label_lines:
        cv2.addWeighted(overlay, 0.25, preview, 0.75, 0, dst=preview)
    return preview


def write_manifest_row(path: Path, row: dict[str, Any]) -> None:
    fieldnames = [
        "image",
        "label",
        "full_image",
        "preview",
        "meta",
        "status",
        "frame_index",
        "width",
        "height",
        "crop_x1",
        "crop_y1",
        "crop_x2",
        "crop_y2",
        "crop_mode",
        "objects",
        "captured_at",
    ]
    exists = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in fieldnames})


def capture(args: argparse.Namespace) -> None:
    output_dir = args.output_dir or Path("chip_seg") / "captures" / datetime.now().strftime("session_%Y%m%d_%H%M%S")
    output_dir = output_dir.resolve()
    for name in ("images", "labels", "images_full", "previews", "meta"):
        (output_dir / name).mkdir(parents=True, exist_ok=True)

    camera_settings = CameraSettings(
        backend=args.backend,
        adb=args.adb,
        serial=args.serial,
        profile=args.profile,
        defect_model_kind="seg",
        remote_defect_model=args.remote_defect_model or CHIP_DEFECT_SEG_REMOTE_MODEL,
        device=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        frames=0,
        skip=args.skip,
        conf=args.conf,
        chip_conf=args.chip_conf,
        defect_conf=args.defect_conf,
        display_max_defects=args.display_max_defects,
        input_adjust=not args.no_input_adjust,
    )
    image_settings = ImageAdjustSettings()
    light_settings = LightSettings(
        rgb=args.light_rgb,
        brightness=args.light_brightness,
        high_brightness=args.light_high_brightness,
        low_brightness=args.light_low_brightness,
        backlight_brightness=args.light_backlight_brightness,
        count=args.light_count,
        device=args.light_device,
        backlight_count=args.backlight_count,
        backlight_gpio=args.backlight_gpio,
        backlight_gpio_chip=args.backlight_gpio_chip,
        backlight_gpio_line=args.backlight_gpio_line,
        backlight_enabled=not args.no_backlight,
    )

    camera = create_camera(camera_settings)
    saved = 0
    seen = 0
    skipped_no_chip = 0
    started = time.perf_counter()
    try:
        if camera_settings.input_adjust:
            write_input_adjust_config(camera_settings)
        if not args.no_light_setup:
            light_controller = create_ws2812_controller(camera_settings, light_settings)
            result = light_controller.set_brightnesses(
                args.light_brightness,
                args.light_high_brightness,
                args.light_low_brightness,
                args.light_backlight_brightness,
            )
            if result:
                print(f"light setup: {result}", flush=True)
        camera.start()
        while saved < args.count:
            elapsed = time.perf_counter() - started
            if args.timeout_sec > 0 and elapsed >= args.timeout_sec:
                print(f"stopped by timeout: saved={saved} seen={seen} elapsed={elapsed:.1f}s", flush=True)
                break
            if args.max_frames > 0 and seen >= args.max_frames:
                print(f"stopped by max frames: saved={saved} seen={seen}", flush=True)
                break
            frame = camera.read_frame()
            if frame is None:
                break
            seen += 1
            if args.progress_interval > 0 and seen % args.progress_interval == 0:
                elapsed = max(0.001, time.perf_counter() - started)
                print(
                    f"progress: saved={saved}/{args.count} seen={seen} skipped_no_chip={skipped_no_chip} elapsed={elapsed:.1f}s",
                    flush=True,
                )
            if args.stride > 1 and seen % args.stride != 0:
                continue
            chip_box = best_chip_box(frame.detections, frame.width, frame.height, args.roi_margin)
            if chip_box is None:
                skipped_no_chip += 1
                if not args.keep_no_chip:
                    continue
                chip_box = (0, 0, frame.width, frame.height)
            x1, y1, x2, y2 = chip_box
            crop = frame.clean_bgr[y1:y2, x1:x2].copy()
            if crop.size == 0:
                continue
            crop_h, crop_w = crop.shape[:2]
            label_lines = defect_prelabels(frame.detections, chip_box, crop_w, crop_h, frame.width, frame.height)
            if args.require_defect and not label_lines:
                continue
            saved += 1
            stem = f"{args.prefix}_{saved:04d}"
            image_path = output_dir / "images" / f"{stem}.jpg"
            label_path = output_dir / "labels" / f"{stem}.txt"
            full_path = output_dir / "images_full" / f"{stem}.jpg"
            preview_path = output_dir / "previews" / f"{stem}.jpg"
            meta_path = output_dir / "meta" / f"{stem}.json"
            write_jpeg(image_path, crop, args.jpeg_quality)
            write_jpeg(full_path, frame.clean_bgr, args.jpeg_quality)
            write_jpeg(preview_path, draw_prelabel_preview(crop, label_lines), args.jpeg_quality)
            label_path.write_text("\n".join(label_lines) + ("\n" if label_lines else ""), encoding="utf-8")
            meta = {
                "captured_at": datetime.now().isoformat(timespec="seconds"),
                "frame_index": frame.frame_index,
                "source_width": frame.width,
                "source_height": frame.height,
                "crop_box": list(chip_box),
                "crop_width": crop_w,
                "crop_height": crop_h,
                "objects": len(label_lines),
                "camera": asdict(camera_settings),
                "image_adjust": image_settings.to_json(),
                "light": light_settings.to_json(),
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            write_manifest_row(
                output_dir / "manifest.csv",
                {
                    "image": session_relative(image_path, output_dir),
                    "label": session_relative(label_path, output_dir),
                    "full_image": session_relative(full_path, output_dir),
                    "preview": session_relative(preview_path, output_dir),
                    "meta": session_relative(meta_path, output_dir),
                    "status": "prelabeled" if label_lines else "empty",
                    "frame_index": frame.frame_index,
                    "width": crop_w,
                    "height": crop_h,
                    "crop_x1": x1,
                    "crop_y1": y1,
                    "crop_x2": x2,
                    "crop_y2": y2,
                    "objects": len(label_lines),
                    "captured_at": meta["captured_at"],
                },
            )
            print(f"saved {saved}/{args.count}: {image_path.name} objects={len(label_lines)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        detail = format_stream_error(camera, exc)
        raise RuntimeError(detail or str(exc)) from exc
    finally:
        camera.stop()
    elapsed = max(0.001, time.perf_counter() - started)
    print(f"capture complete: saved={saved} seen={seen} skipped_no_chip={skipped_no_chip} elapsed={elapsed:.1f}s")
    print(f"output: {output_dir}")


def read_capture_items(input_dir: Path) -> list[dict[str, Any]]:
    manifest = input_dir / "manifest.csv"
    if manifest.exists():
        with manifest.open("r", newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        resolved_rows: list[dict[str, Any]] = []
        for row in rows:
            image_name = Path(row.get("image") or "").name
            if not image_name:
                continue
            stem = Path(image_name).stem
            fixed = dict(row)
            fixed["image"] = str(resolve_capture_path(input_dir, row.get("image"), "images", image_name))
            fixed["label"] = str(resolve_capture_path(input_dir, row.get("label"), "labels", f"{stem}.txt"))
            resolved_rows.append(fixed)
        return resolved_rows
    items: list[dict[str, Any]] = []
    for image_path in sorted((input_dir / "images").iterdir()):
        if image_path.suffix.lower() not in IMAGE_EXTS:
            continue
        label_path = input_dir / "labels" / f"{image_path.stem}.txt"
        items.append({"image": str(image_path), "label": str(label_path), "status": "unknown"})
    return items


def coco_from_items(items: list[dict[str, Any]], images_dir: Path, labels_dir: Path) -> dict[str, Any]:
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    ann_id = 1
    for image_id, item in enumerate(items, start=1):
        image_path = Path(item["image"])
        copied_image = images_dir / image_path.name
        image = read_image(copied_image)
        height, width = image.shape[:2]
        images.append(
            {
                "id": image_id,
                "file_name": f"{CVAT_COCO_SUBSET}/{copied_image.name}",
                "width": width,
                "height": height,
            }
        )
        label_path = Path(item.get("label") or labels_dir / f"{image_path.stem}.txt")
        if not label_path.exists():
            continue
        for raw_line in label_path.read_text(encoding="utf-8").splitlines():
            parsed = yolo_line_to_polygon(raw_line, width, height)
            if parsed is None:
                continue
            cls_id, points = parsed
            segmentation = [coord for point in points for coord in point]
            annotations.append(
                {
                    "id": ann_id,
                    "image_id": image_id,
                    "category_id": cls_id + 1,
                    "segmentation": [segmentation],
                    "area": polygon_area(points),
                    "bbox": bbox_from_points(points),
                    "iscrowd": 0,
                }
            )
            ann_id += 1
    return {
        "images": images,
        "annotations": annotations,
        "categories": [{"id": idx + 1, "name": name, "supercategory": "defect"} for idx, name in enumerate(CLASS_NAMES)],
    }


def package_cvat(args: argparse.Namespace) -> None:
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    items = read_capture_items(input_dir)
    if not items:
        raise RuntimeError(f"no capture items found in {input_dir}")
    chunk_size = max(1, int(args.chunk_size))
    for part_index, start in enumerate(range(0, len(items), chunk_size), start=1):
        part_items = items[start : start + chunk_size]
        part_dir = output_dir / f"part_{part_index:03d}"
        images_dir = part_dir / "images" / CVAT_COCO_SUBSET
        labels_dir = part_dir / "labels"
        annotations_dir = part_dir / "annotations"
        for directory in (images_dir, labels_dir, annotations_dir):
            directory.mkdir(parents=True, exist_ok=True)
        copied_items: list[dict[str, Any]] = []
        for item in part_items:
            image_path = Path(item["image"])
            label_path = Path(item.get("label") or "")
            dst_image = images_dir / image_path.name
            shutil.copy2(image_path, dst_image)
            dst_label = labels_dir / f"{image_path.stem}.txt"
            if label_path.exists():
                shutil.copy2(label_path, dst_label)
            else:
                dst_label.write_text("", encoding="utf-8")
            copied = dict(item)
            copied["image"] = str(dst_image)
            copied["label"] = str(dst_label)
            copied_items.append(copied)
        coco = coco_from_items(copied_items, images_dir, labels_dir)
        (annotations_dir / "instances_default.json").write_text(json.dumps(coco, ensure_ascii=False, indent=2), encoding="utf-8")
        (part_dir / "labels.txt").write_text("\n".join(CLASS_NAMES) + "\n", encoding="utf-8")
        with (part_dir / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            fieldnames = sorted({key for item in copied_items for key in item.keys()})
            writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(copied_items)
        if args.zip:
            zip_path = output_dir / f"{part_dir.name}.zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(part_dir.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(part_dir))
        print(f"wrote {part_dir} images={len(part_items)} annotations={len(coco['annotations'])}")


def iter_coco_inputs(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".json":
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(path.glob("**/instances*.json")))
    return sorted(set(found))


def extract_coco_zip_inputs(paths: list[Path]) -> tuple[list[Path], tempfile.TemporaryDirectory[str] | None]:
    zip_paths = [path for path in paths if path.is_file() and path.suffix.lower() == ".zip"]
    if not zip_paths:
        return paths, None
    temp_dir = tempfile.TemporaryDirectory(prefix="chip_seg_cvat_exports_")
    expanded: list[Path] = [path for path in paths if path not in zip_paths]
    for index, zip_path in enumerate(zip_paths, start=1):
        extract_dir = Path(temp_dir.name) / f"zip_{index:03d}_{zip_path.stem}"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)
        expanded.append(extract_dir)
    return expanded, temp_dir


def category_map(coco: dict[str, Any]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for category in coco.get("categories", []):
        cat_id = int(category["id"])
        name = str(category.get("name", ""))
        if name in CLASS_NAMES:
            mapping[cat_id] = CLASS_NAMES.index(name)
        elif 1 <= cat_id <= len(CLASS_NAMES):
            mapping[cat_id] = cat_id - 1
    return mapping


def source_image_for(coco_path: Path, file_name: str) -> Path:
    file_path = Path(file_name)
    image_name = file_path.name
    candidates = [
        coco_path.parent.parent / "images" / file_path,
        coco_path.parent.parent / "images" / image_name,
        coco_path.parent / image_name,
        coco_path.parent.parent / image_name,
        coco_path.parent / "images" / file_path,
        coco_path.parent / "images" / image_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for parent in [coco_path.parent, coco_path.parent.parent, *coco_path.parents]:
        matches = list(parent.glob(f"**/{image_name}"))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"cannot resolve image {file_name!r} near {coco_path}")


def collect_coco_records(coco_paths: list[Path]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    used_stems: set[str] = set()
    stats = {
        "images": 0,
        "annotations": 0,
        "polygon_annotations": 0,
        "rle_annotations": 0,
        "written_objects": 0,
        "skipped_annotations": 0,
    }
    for coco_path in coco_paths:
        coco = json.loads(coco_path.read_text(encoding="utf-8"))
        cat_to_cls = category_map(coco)
        anns_by_image: dict[int, list[dict[str, Any]]] = {}
        for ann in coco.get("annotations", []):
            anns_by_image.setdefault(int(ann["image_id"]), []).append(ann)
        for image_info in coco.get("images", []):
            stats["images"] += 1
            image_id = int(image_info["id"])
            src_image = source_image_for(coco_path, str(image_info["file_name"]))
            stem_base = Path(image_info["file_name"]).stem.replace(" ", "_")
            stem = stem_base
            suffix = 2
            while stem in used_stems:
                stem = f"{stem_base}_{suffix}"
                suffix += 1
            used_stems.add(stem)
            width = int(image_info.get("width") or read_image(src_image).shape[1])
            height = int(image_info.get("height") or read_image(src_image).shape[0])
            yolo_lines: list[str] = []
            for ann in anns_by_image.get(image_id, []):
                stats["annotations"] += 1
                cls_id = cat_to_cls.get(int(ann.get("category_id", -1)))
                if cls_id is None:
                    stats["skipped_annotations"] += 1
                    continue
                segmentation = ann.get("segmentation", [])
                if isinstance(segmentation, dict):
                    stats["rle_annotations"] += 1
                    mask = decode_coco_rle(segmentation, width, height)
                    if mask is None:
                        stats["skipped_annotations"] += 1
                        continue
                    before = len(yolo_lines)
                    for points in mask_to_polygons(mask):
                        line = polygon_to_yolo_line(cls_id, points, width, height)
                        if line:
                            yolo_lines.append(line)
                    if len(yolo_lines) == before:
                        stats["skipped_annotations"] += 1
                    continue
                wrote_polygon = False
                for seg in segmentation:
                    if not isinstance(seg, list) or len(seg) < 6:
                        continue
                    points = [(float(seg[i]), float(seg[i + 1])) for i in range(0, len(seg), 2)]
                    line = polygon_to_yolo_line(cls_id, points, width, height)
                    if line:
                        yolo_lines.append(line)
                        wrote_polygon = True
                stats["polygon_annotations"] += 1
                if not wrote_polygon:
                    stats["skipped_annotations"] += 1
            stats["written_objects"] += len(yolo_lines)
            records.append({"src_image": src_image, "stem": stem, "width": width, "height": height, "labels": yolo_lines})
    return records, stats


def split_records(records: list[dict[str, Any]], ratios: str, seed: int) -> dict[str, list[dict[str, Any]]]:
    parts = [float(part.strip()) for part in ratios.split(",")]
    if len(parts) != 3 or any(part < 0 for part in parts) or sum(parts) <= 0:
        raise ValueError("--splits must be three non-negative numbers, e.g. 0.8,0.1,0.1")
    total = sum(parts)
    parts = [part / total for part in parts]
    rng = random.Random(seed)
    shuffled = list(records)
    rng.shuffle(shuffled)
    train_end = int(round(len(shuffled) * parts[0]))
    valid_end = train_end + int(round(len(shuffled) * parts[1]))
    return {
        "train": shuffled[:train_end],
        "valid": shuffled[train_end:valid_end],
        "test": shuffled[valid_end:],
    }


def merge_coco(args: argparse.Namespace) -> None:
    expanded_inputs, temp_dir = extract_coco_zip_inputs(args.inputs)
    try:
        coco_paths = iter_coco_inputs(expanded_inputs)
        if not coco_paths:
            raise RuntimeError("no COCO json files found")
        records, collect_stats = collect_coco_records(coco_paths)
        if not records:
            raise RuntimeError("no images found in COCO inputs")
        output_dir = args.output_dir.resolve()
        if output_dir.exists():
            if not args.overwrite:
                raise FileExistsError(f"{output_dir} exists; use --overwrite")
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        splits = split_records(records, args.splits, args.seed)
        report: dict[str, Any] = {
            "source_coco": [str(path) for path in coco_paths],
            "source_inputs": [str(path) for path in args.inputs],
            "splits": {},
            "class_names": CLASS_NAMES,
            "collect_stats": collect_stats,
        }
        for split, split_records_list in splits.items():
            image_dir = output_dir / split / "images"
            label_dir = output_dir / split / "labels"
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            object_count = 0
            empty_count = 0
            for record in split_records_list:
                dst_image = image_dir / f"{record['stem']}{record['src_image'].suffix.lower()}"
                shutil.copy2(record["src_image"], dst_image)
                label_path = label_dir / f"{record['stem']}.txt"
                labels = record["labels"]
                object_count += len(labels)
                if not labels:
                    empty_count += 1
                label_path.write_text("\n".join(labels) + ("\n" if labels else ""), encoding="utf-8")
            report["splits"][split] = {"images": len(split_records_list), "objects": object_count, "empty_images": empty_count}
        names_lines = "\n".join(f"  {idx}: {name}" for idx, name in enumerate(CLASS_NAMES))
        (output_dir / "data.yaml").write_text(
            f"path: {output_dir.as_posix()}\ntrain: train/images\nval: valid/images\ntest: test/images\nnc: 4\nnames:\n{names_lines}\n",
            encoding="utf-8",
        )
        (output_dir / "names.txt").write_text("\n".join(CLASS_NAMES) + "\n", encoding="utf-8")
        (output_dir / "merge_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report["splits"], ensure_ascii=False, indent=2))
        print(f"wrote {output_dir}")
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def add_camera_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", choices=("adb", "local"), default="adb")
    parser.add_argument("--adb", default=default_adb_path())
    parser.add_argument("--serial", default=DEFAULT_SERIAL)
    parser.add_argument("--profile", default="chip-two-stage-seg-imx678")
    parser.add_argument("--remote-defect-model", default=CHIP_DEFECT_SEG_REMOTE_MODEL)
    parser.add_argument("--device", default="/dev/video73")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--skip", type=int, default=3)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--chip-conf", type=float, default=0.25)
    parser.add_argument("--defect-conf", type=float, default=0.45)
    parser.add_argument("--display-max-defects", type=int, default=20)
    parser.add_argument("--roi-margin", type=float, default=0.08)
    parser.add_argument("--no-input-adjust", action="store_true")
    parser.add_argument("--light-brightness", type=float, default=0.50)
    parser.add_argument("--light-high-brightness", type=float, default=0.20)
    parser.add_argument("--light-low-brightness", type=float, default=0.20)
    parser.add_argument("--light-backlight-brightness", type=float, default=0.20)
    parser.add_argument("--light-rgb", type=parse_rgb, default=parse_rgb("190,255,100"))
    parser.add_argument("--light-count", type=int, default=44)
    parser.add_argument("--light-device", default="/dev/spidev1.0")
    parser.add_argument("--backlight-gpio", default="GPIO3_A2")
    parser.add_argument("--backlight-gpio-chip", default="gpiochip3")
    parser.add_argument("--backlight-gpio-line", type=int, default=2)
    parser.add_argument("--backlight-count", type=int, default=256)
    parser.add_argument("--no-backlight", action="store_true")
    parser.add_argument("--no-light-setup", action="store_true", help="Do not change WS2812 brightness before capture")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture", help="Capture chip ROI crops and current seg prelabels")
    add_camera_args(capture_parser)
    capture_parser.add_argument("--output-dir", type=Path)
    capture_parser.add_argument("--count", type=int, default=100)
    capture_parser.add_argument("--stride", type=int, default=8)
    capture_parser.add_argument("--max-frames", type=int, default=0, help="Stop after reading this many frames; 0 disables")
    capture_parser.add_argument("--timeout-sec", type=float, default=3600.0, help="Stop after this many seconds; 0 disables")
    capture_parser.add_argument("--progress-interval", type=int, default=100, help="Print capture progress every N read frames; 0 disables")
    capture_parser.add_argument("--prefix", default="seg")
    capture_parser.add_argument("--jpeg-quality", type=int, default=95)
    capture_parser.add_argument("--keep-no-chip", action="store_true")
    capture_parser.add_argument("--require-defect", action="store_true")
    capture_parser.set_defaults(func=capture)

    package_parser = subparsers.add_parser("package-cvat", help="Split captures into CVAT task folders")
    package_parser.add_argument("--input-dir", required=True, type=Path)
    package_parser.add_argument("--output-dir", required=True, type=Path)
    package_parser.add_argument("--chunk-size", type=int, default=100)
    package_parser.add_argument("--zip", action="store_true", help="Also create one zip per part")
    package_parser.set_defaults(func=package_cvat)

    merge_parser = subparsers.add_parser("merge-coco", help="Merge CVAT COCO exports into YOLOv8-seg raw dataset")
    merge_parser.add_argument("--inputs", required=True, nargs="+", type=Path)
    merge_parser.add_argument("--output-dir", required=True, type=Path)
    merge_parser.add_argument("--splits", default="0.8,0.1,0.1")
    merge_parser.add_argument("--seed", type=int, default=42)
    merge_parser.add_argument("--overwrite", action="store_true")
    merge_parser.set_defaults(func=merge_coco)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

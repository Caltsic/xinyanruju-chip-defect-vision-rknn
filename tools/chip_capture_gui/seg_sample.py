from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from tools.adb_imx415_rknn_live_view import Detection, normalize_points
from tools.seg_cvat_pipeline import (
    CLASS_NAMES,
    best_chip_box,
    clip_polygon_to_rect,
    defect_prelabels,
    draw_prelabel_preview,
    detection_points,
    polygon_to_yolo_line,
    session_relative,
    write_jpeg,
    write_manifest_row,
)

from .models import CameraFrame
from .obb_refine import refine_chip_obbs_in_frame
from .settings import CameraSettings, ImageAdjustSettings, LightSettings, PROJECT_ROOT


SEG_SAMPLE_PREFIX = "seg"


@dataclass(slots=True)
class ObbCrop:
    image: object
    label_lines: list[str]
    crop_box: tuple[int, int, int, int]
    crop_width: int
    crop_height: int
    points: list[tuple[float, float]]
    crop_to_full: list[float]
    full_to_crop: list[float]


def _best_chip_obb(detections: list[Detection], width: int, height: int) -> list[tuple[float, float]] | None:
    best: tuple[float, list[tuple[float, float]]] | None = None
    for detection in detections:
        if detection.class_id != 0 or not detection.obb_points:
            continue
        points = normalize_points(detection.obb_points, width, height)
        if len(points) != 4:
            continue
        area = abs(
            sum(
                x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
            )
        ) * 0.5
        if area <= 4.0:
            continue
        rank = max(0.001, float(detection.score)) * area
        if best is None or rank > best[0]:
            best = (rank, points)
    return None if best is None else best[1]


def _apply_affine(matrix: np.ndarray, point: tuple[float, float]) -> tuple[float, float]:
    x, y = point
    return (
        float(matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2]),
        float(matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2]),
    )


def _defect_prelabels_for_obb(
    detections: list[Detection],
    full_to_crop: np.ndarray,
    crop_w: int,
    crop_h: int,
    frame_w: int,
    frame_h: int,
) -> list[str]:
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
        crop_points = [_apply_affine(full_to_crop, point) for point in full_points]
        clipped_points = clip_polygon_to_rect(
            crop_points,
            0.0,
            0.0,
            float(crop_w - 1),
            float(crop_h - 1),
        )
        line = polygon_to_yolo_line(cls_id, clipped_points, crop_w, crop_h)
        if line:
            lines.append(line)
    return lines


def _try_obb_crop(frame: CameraFrame, roi_margin: float) -> ObbCrop | None:
    points = _best_chip_obb(frame.detections, frame.width, frame.height)
    if points is None:
        return None
    p0, p1, p2, p3 = points
    edge_w = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    edge_h = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if edge_w < 2.0 or edge_h < 2.0:
        return None
    scale = 1.0 + 2.0 * max(0.0, roi_margin)
    crop_w = max(2, int(math.ceil(edge_w * scale)))
    crop_h = max(2, int(math.ceil(edge_h * scale)))
    cx = sum(point[0] for point in points) / 4.0
    cy = sum(point[1] for point in points) / 4.0
    angle = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    half_w = crop_w * 0.5
    half_h = crop_h * 0.5
    crop_to_full = np.array(
        [
            [cos_a, -sin_a, cx - half_w * cos_a + half_h * sin_a],
            [sin_a, cos_a, cy - half_w * sin_a - half_h * cos_a],
        ],
        dtype=np.float32,
    )
    full_to_crop = cv2.invertAffineTransform(crop_to_full)
    crop = cv2.warpAffine(
        frame.clean_bgr,
        full_to_crop,
        (crop_w, crop_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(114, 114, 114),
    )
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    crop_box = (
        max(0, min(frame.width - 1, int(math.floor(min(xs))))),
        max(0, min(frame.height - 1, int(math.floor(min(ys))))),
        max(0, min(frame.width, int(math.ceil(max(xs))))),
        max(0, min(frame.height, int(math.ceil(max(ys))))),
    )
    label_lines = _defect_prelabels_for_obb(
        frame.detections,
        full_to_crop,
        crop_w,
        crop_h,
        frame.width,
        frame.height,
    )
    return ObbCrop(
        image=crop,
        label_lines=label_lines,
        crop_box=crop_box,
        crop_width=crop_w,
        crop_height=crop_h,
        points=points,
        crop_to_full=[float(value) for value in crop_to_full.reshape(-1)],
        full_to_crop=[float(value) for value in full_to_crop.reshape(-1)],
    )


@dataclass(slots=True)
class SegSampleResult:
    stem: str
    image_path: Path
    label_path: Path
    full_image_path: Path
    preview_path: Path
    meta_path: Path
    crop_box: tuple[int, int, int, int]
    crop_width: int
    crop_height: int
    objects: int


def default_seg_output_dir() -> Path:
    stamp = datetime.now().strftime("gui_session_%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "chip_seg" / "captures" / stamp


class SegSampleWriter:
    def __init__(self, output_dir: Path | None = None, prefix: str = SEG_SAMPLE_PREFIX, jpeg_quality: int = 95) -> None:
        self.output_dir = (output_dir or default_seg_output_dir()).resolve()
        self.prefix = prefix
        self.jpeg_quality = jpeg_quality
        self._next_index = 1
        for name in ("images", "labels", "images_full", "previews", "meta"):
            (self.output_dir / name).mkdir(parents=True, exist_ok=True)
        self._next_index = self._first_available_index()

    def next_stem(self) -> str:
        return f"{self.prefix}_{self._next_index:04d}"

    def save(
        self,
        frame: CameraFrame,
        camera_settings: CameraSettings,
        image_settings: ImageAdjustSettings,
        light_settings: LightSettings,
    ) -> SegSampleResult | None:
        refine_chip_obbs_in_frame(frame.clean_bgr, frame.detections, frame.width, frame.height)
        obb_crop = _try_obb_crop(frame, camera_settings.roi_margin)
        crop_mode = "obb" if obb_crop is not None else "hbb"
        if obb_crop is not None:
            chip_box = obb_crop.crop_box
            crop = obb_crop.image
            crop_w = obb_crop.crop_width
            crop_h = obb_crop.crop_height
            label_lines = obb_crop.label_lines
        else:
            chip_box = best_chip_box(frame.detections, frame.width, frame.height, camera_settings.roi_margin)
            if chip_box is None:
                return None
            x1, y1, x2, y2 = chip_box
            crop = frame.clean_bgr[y1:y2, x1:x2].copy()
            if crop.size == 0:
                return None
            crop_h, crop_w = crop.shape[:2]
            label_lines = defect_prelabels(frame.detections, chip_box, crop_w, crop_h, frame.width, frame.height)
        x1, y1, x2, y2 = chip_box

        stem = self._reserve_stem()
        image_path = self.output_dir / "images" / f"{stem}.jpg"
        label_path = self.output_dir / "labels" / f"{stem}.txt"
        full_path = self.output_dir / "images_full" / f"{stem}.jpg"
        preview_path = self.output_dir / "previews" / f"{stem}.jpg"
        meta_path = self.output_dir / "meta" / f"{stem}.json"

        write_jpeg(image_path, crop, self.jpeg_quality)
        write_jpeg(full_path, frame.clean_bgr, self.jpeg_quality)
        write_jpeg(preview_path, draw_prelabel_preview(crop, label_lines), self.jpeg_quality)
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text("\n".join(label_lines) + ("\n" if label_lines else ""), encoding="utf-8")

        captured_at = datetime.now().isoformat(timespec="seconds")
        meta = {
            "captured_at": captured_at,
            "frame_index": frame.frame_index,
            "source_width": frame.width,
            "source_height": frame.height,
            "crop_mode": crop_mode,
            "crop_box": list(chip_box),
            "crop_width": crop_w,
            "crop_height": crop_h,
            "objects": len(label_lines),
            "class_names": list(CLASS_NAMES),
            "camera": asdict(camera_settings),
            "image_adjust": image_settings.to_json(),
            "light": light_settings.to_json(),
        }
        if obb_crop is not None:
            meta.update(
                {
                    "crop_obb_points": [[float(x), float(y)] for x, y in obb_crop.points],
                    "crop_to_full_affine": obb_crop.crop_to_full,
                    "full_to_crop_affine": obb_crop.full_to_crop,
                }
            )
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        write_manifest_row(
            self.output_dir / "manifest.csv",
            {
                "image": session_relative(image_path, self.output_dir),
                "label": session_relative(label_path, self.output_dir),
                "full_image": session_relative(full_path, self.output_dir),
                "preview": session_relative(preview_path, self.output_dir),
                "meta": session_relative(meta_path, self.output_dir),
                "status": "prelabeled" if label_lines else "empty",
                "frame_index": frame.frame_index,
                "width": crop_w,
                "height": crop_h,
                "crop_x1": x1,
                "crop_y1": y1,
                "crop_x2": x2,
                "crop_y2": y2,
                "crop_mode": crop_mode,
                "objects": len(label_lines),
                "captured_at": captured_at,
            },
        )
        self._next_index += 1
        return SegSampleResult(
            stem=stem,
            image_path=image_path,
            label_path=label_path,
            full_image_path=full_path,
            preview_path=preview_path,
            meta_path=meta_path,
            crop_box=chip_box,
            crop_width=crop_w,
            crop_height=crop_h,
            objects=len(label_lines),
        )

    def _first_available_index(self) -> int:
        index = 1
        while self._paths_exist(f"{self.prefix}_{index:04d}"):
            index += 1
        return index

    def _reserve_stem(self) -> str:
        while True:
            stem = self.next_stem()
            if not self._paths_exist(stem):
                return stem
            self._next_index += 1

    def _paths_exist(self, stem: str) -> bool:
        candidates = (
            self.output_dir / "images" / f"{stem}.jpg",
            self.output_dir / "labels" / f"{stem}.txt",
            self.output_dir / "images_full" / f"{stem}.jpg",
            self.output_dir / "previews" / f"{stem}.jpg",
            self.output_dir / "meta" / f"{stem}.json",
        )
        return any(path.exists() for path in candidates)

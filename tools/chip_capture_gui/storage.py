from __future__ import annotations

import csv
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from tools.chip_roi_utils import box_to_yolo, draw_chip_box

from .models import CameraFrame
from .settings import CameraSettings, ImageAdjustSettings, LightSettings


@dataclass(slots=True)
class ChipRoiRecord:
    image_path: Path
    label_path: Path
    meta_path: Path
    preview_path: Path
    manifest_path: Path
    stem: str
    index: int
    width: int
    height: int
    method: str
    score: float


class CaptureStorage:
    def __init__(self, output_dir: Path, jpeg_quality: int = 95) -> None:
        self.output_dir = output_dir
        self.jpeg_quality = max(1, min(100, jpeg_quality))

    def set_output_dir(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def next_sequence(self, prefix: str) -> int:
        images_dir = self.output_dir / "images"
        if not images_dir.exists():
            return 1
        max_index = 0
        for path in images_dir.glob(f"{prefix}_*.jpg"):
            suffix = path.stem.removeprefix(f"{prefix}_")
            if suffix.isdigit():
                max_index = max(max_index, int(suffix))
        return max_index + 1

    def next_stem(self, prefix: str) -> str:
        return f"{prefix}_{self.next_sequence(prefix):04d}"

    def save(
        self,
        frame: CameraFrame,
        clean_bgr: np.ndarray,
        annotated_bgr: np.ndarray,
        camera_settings: CameraSettings,
        image_settings: ImageAdjustSettings,
        light_settings: LightSettings,
        drawn_count: int,
    ) -> tuple[Path, Path, Path]:
        clean_dir = self.output_dir / "clean"
        annotated_dir = self.output_dir / "annotated"
        meta_dir = self.output_dir / "meta"
        clean_dir.mkdir(parents=True, exist_ok=True)
        annotated_dir.mkdir(parents=True, exist_ok=True)
        meta_dir.mkdir(parents=True, exist_ok=True)

        stem = self._stem(frame, light_settings)
        clean_path = clean_dir / f"{stem}.jpg"
        annotated_path = annotated_dir / f"{stem}.jpg"
        meta_path = meta_dir / f"{stem}.json"

        self._write_jpeg(clean_path, clean_bgr)
        self._write_jpeg(annotated_path, annotated_bgr)
        meta_path.write_text(
            json.dumps(
                self._metadata(
                    frame=frame,
                    clean_path=clean_path,
                    annotated_path=annotated_path,
                    camera_settings=camera_settings,
                    image_settings=image_settings,
                    light_settings=light_settings,
                    drawn_count=drawn_count,
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return clean_path, annotated_path, meta_path

    def save_chip_roi_candidate(
        self,
        frame: CameraFrame,
        clean_bgr: np.ndarray,
        chip_box: tuple[int, int, int, int] | None,
        camera_settings: CameraSettings,
        image_settings: ImageAdjustSettings,
        light_settings: LightSettings,
        prefix: str,
        method: str,
        score: float,
        capture_adjusted: bool = False,
    ) -> ChipRoiRecord:
        images_dir = self.output_dir / "images"
        labels_dir = self.output_dir / "labels"
        meta_dir = self.output_dir / "meta"
        previews_dir = self.output_dir / "previews"
        for directory in (images_dir, labels_dir, meta_dir, previews_dir):
            directory.mkdir(parents=True, exist_ok=True)

        index = self.next_sequence(prefix)
        stem = f"{prefix}_{index:04d}"
        image_path = images_dir / f"{stem}.jpg"
        label_path = labels_dir / f"{stem}.txt"
        meta_path = meta_dir / f"{stem}.json"
        preview_path = previews_dir / f"{stem}.jpg"
        manifest_path = self.output_dir / "manifest.csv"

        self._write_jpeg(image_path, clean_bgr)
        self._write_chip_label(label_path, chip_box, frame.width, frame.height)
        self._write_jpeg(preview_path, draw_chip_box(clean_bgr, chip_box, f"{stem} candidate"))
        meta_path.write_text(
            json.dumps(
                {
                    "timestamp": datetime.fromtimestamp(frame.timestamp).isoformat(timespec="milliseconds"),
                    "frame_index": frame.frame_index,
                    "width": frame.width,
                    "height": frame.height,
                    "fps": frame.fps,
                    "focus": frame.focus,
                    "image": str(image_path),
                    "label": str(label_path),
                    "preview": str(preview_path),
                    "roi_method": method,
                    "roi_score": score,
                    "chip_box": list(chip_box) if chip_box is not None else None,
                    "capture_adjusted": capture_adjusted,
                    "camera": asdict(camera_settings),
                    "image_adjust": image_settings.to_json(),
                    "light": light_settings.to_json(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        record = ChipRoiRecord(
            image_path=image_path,
            label_path=label_path,
            meta_path=meta_path,
            preview_path=preview_path,
            manifest_path=manifest_path,
            stem=stem,
            index=index,
            width=frame.width,
            height=frame.height,
            method=method,
            score=score,
        )
        return record

    def update_chip_roi_label(
        self,
        record: ChipRoiRecord,
        clean_bgr: np.ndarray,
        chip_box: tuple[int, int, int, int] | None,
        status: str,
    ) -> None:
        self._write_chip_label(record.label_path, chip_box, record.width, record.height)
        self._write_jpeg(record.preview_path, draw_chip_box(clean_bgr, chip_box, f"{record.stem} {status}"))
        self._upsert_manifest(record, chip_box, status)

    def _stem(self, frame: CameraFrame, light_settings: LightSettings) -> str:
        timestamp = datetime.fromtimestamp(frame.timestamp).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        brightness_pct = int(round(light_settings.brightness * 100))
        return f"{timestamp}_f{frame.frame_index:06d}_b{brightness_pct:02d}"

    def _write_jpeg(self, path: Path, image: np.ndarray) -> None:
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            raise RuntimeError(f"failed to encode {path}")
        path.write_bytes(encoded.tobytes())

    def _write_chip_label(
        self,
        path: Path,
        chip_box: tuple[int, int, int, int] | None,
        width: int,
        height: int,
    ) -> None:
        if chip_box is None:
            path.write_text("", encoding="utf-8")
            return
        path.write_text(box_to_yolo(chip_box, width, height) + "\n", encoding="utf-8")

    def _upsert_manifest(
        self,
        record: ChipRoiRecord,
        chip_box: tuple[int, int, int, int] | None,
        status: str,
    ) -> None:
        fieldnames = [
            "image",
            "label",
            "split",
            "source",
            "status",
            "width",
            "height",
            "x1",
            "y1",
            "x2",
            "y2",
            "score",
            "method",
            "reviewed_at",
        ]
        rows: list[dict[str, str]] = []
        if record.manifest_path.exists():
            try:
                with record.manifest_path.open("r", newline="", encoding="utf-8-sig") as stream:
                    reader = csv.DictReader(stream)
                    rows = list(reader)
            except PermissionError as exc:
                raise RuntimeError(f"manifest locked, close it and retry: {record.manifest_path}") from exc
        row = {
            "image": str(record.image_path.resolve()),
            "label": str(record.label_path.resolve()),
            "split": "captures",
            "source": "chip_capture_gui",
            "status": status,
            "width": str(record.width),
            "height": str(record.height),
            "x1": "" if chip_box is None else str(chip_box[0]),
            "y1": "" if chip_box is None else str(chip_box[1]),
            "x2": "" if chip_box is None else str(chip_box[2]),
            "y2": "" if chip_box is None else str(chip_box[3]),
            "score": f"{record.score:.6f}",
            "method": record.method,
            "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        }
        replaced = False
        for index, old in enumerate(rows):
            if old.get("image") == row["image"] or old.get("label") == row["label"]:
                rows[index] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        try:
            with record.manifest_path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
        except PermissionError as exc:
            raise RuntimeError(f"manifest locked, close it and retry: {record.manifest_path}") from exc

    def _metadata(
        self,
        frame: CameraFrame,
        clean_path: Path,
        annotated_path: Path,
        camera_settings: CameraSettings,
        image_settings: ImageAdjustSettings,
        light_settings: LightSettings,
        drawn_count: int,
    ) -> dict[str, Any]:
        return {
            "timestamp": datetime.fromtimestamp(frame.timestamp).isoformat(timespec="milliseconds"),
            "frame_index": frame.frame_index,
            "width": frame.width,
            "height": frame.height,
            "fps": frame.fps,
            "focus": frame.focus,
            "detections_raw": len(frame.detections),
            "detections_drawn": drawn_count,
            "clean": str(clean_path),
            "annotated": str(annotated_path),
            "camera": asdict(camera_settings),
            "image_adjust": image_settings.to_json(),
            "light": light_settings.to_json(),
        }

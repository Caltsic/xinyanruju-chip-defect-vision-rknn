from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .models import CameraFrame
from .settings import CameraSettings, ImageAdjustSettings, LightSettings


class CaptureStorage:
    def __init__(self, output_dir: Path, jpeg_quality: int = 95) -> None:
        self.output_dir = output_dir
        self.jpeg_quality = max(1, min(100, jpeg_quality))

    def set_output_dir(self, output_dir: Path) -> None:
        self.output_dir = output_dir

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

    def _stem(self, frame: CameraFrame, light_settings: LightSettings) -> str:
        timestamp = datetime.fromtimestamp(frame.timestamp).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        brightness_pct = int(round(light_settings.brightness * 100))
        return f"{timestamp}_f{frame.frame_index:06d}_b{brightness_pct:02d}"

    def _write_jpeg(self, path: Path, image: np.ndarray) -> None:
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            raise RuntimeError(f"failed to encode {path}")
        path.write_bytes(encoded.tobytes())

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

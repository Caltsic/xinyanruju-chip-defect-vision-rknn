from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from tools.adb_imx415_rknn_live_view import Detection


@dataclass(slots=True)
class CameraFrame:
    clean_bgr: Any
    width: int
    height: int
    frame_index: int
    detections: list[Detection]
    fps: float
    focus: float
    timestamp: float

    @classmethod
    def from_parts(
        cls,
        clean_bgr: Any,
        width: int,
        height: int,
        frame_index: int,
        detections: list[Detection],
        fps: float,
        focus: float,
    ) -> "CameraFrame":
        return cls(
            clean_bgr=clean_bgr,
            width=width,
            height=height,
            frame_index=frame_index,
            detections=detections,
            fps=fps,
            focus=focus,
            timestamp=time.time(),
        )

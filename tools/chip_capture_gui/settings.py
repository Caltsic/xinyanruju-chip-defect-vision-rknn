from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tools.adb_imx415_rknn_live_view import (
    CHIP_REMOTE_WORKDIR,
    CHIP_ROI_REMOTE_MODEL,
    CHIP_TWO_STAGE_MAIXCAM_REMOTE_BINARY,
    DEFAULT_CONF,
    DEFAULT_NMS,
    DEFAULT_REMOTE_LOG,
    DEFAULT_SERIAL,
    default_adb_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "chip_roi" / "generated" / "gui_capture"


@dataclass(slots=True)
class CameraSettings:
    adb: str = default_adb_path()
    serial: str = DEFAULT_SERIAL
    profile: str = "chip-two-stage-maixcam"
    remote_workdir: str = CHIP_REMOTE_WORKDIR
    remote_binary: str = CHIP_TWO_STAGE_MAIXCAM_REMOTE_BINARY
    remote_model: str = CHIP_ROI_REMOTE_MODEL
    device: str = "/dev/video73"
    width: int = 1280
    height: int = 720
    fps: int = 30
    frames: int = 0
    skip: int = 3
    conf: float = DEFAULT_CONF
    chip_conf: float = 0.25
    defect_conf: float = 0.45
    roi_margin: float = 0.08
    roi_smooth_alpha: float = 0.35
    roi_hold: int = 3
    chip_interval: int = 3
    defect_interval: int = 2
    defect_confirm: int = 3
    defect_hold: int = 3
    defect_smooth_alpha: float = 0.35
    defect_match_iou: float = 0.10
    defect_match_center: float = 0.55
    defect_class_decay: float = 0.85
    nms: float = DEFAULT_NMS
    camera_format: str | None = "mjpg"
    roi: str | None = None
    remote_log: str = DEFAULT_REMOTE_LOG
    display_max_defects: int = 20
    display_nms: float = 0.30
    no_display_filter: bool = False
    input_adjust: bool = True
    input_brightness: int = -6
    input_contrast: float = 1.28
    input_gamma: float = 0.91
    input_saturation: float = 0.30
    input_sharpness: float = 0.85
    input_adjust_file: str = "/tmp/chip_input_adjust.conf"

    def to_namespace(self) -> SimpleNamespace:
        return SimpleNamespace(**asdict(self))


@dataclass(slots=True)
class ImageAdjustSettings:
    brightness: int = -6
    contrast: float = 1.28
    gamma: float = 0.91
    saturation: float = 0.30
    sharpness: float = 0.85
    denoise: int = 6
    clahe_enabled: bool = False
    clahe_clip_limit: float = 2.0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LightSettings:
    rgb: tuple[int, int, int] = (190, 255, 100)
    brightness: float = 0.50
    max_brightness: float = 0.80
    count: int = 8
    device: str = "/dev/spidev1.0"

    def rgb_text(self) -> str:
        return ",".join(str(channel) for channel in self.rgb)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["rgb"] = list(self.rgb)
        return data

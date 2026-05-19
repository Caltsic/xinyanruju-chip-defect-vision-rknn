from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tools.adb_imx415_rknn_live_view import (
    CHIP_ROI_OBB_REMOTE_MODEL,
    CHIP_REMOTE_WORKDIR,
    CHIP_REMOTE_MODEL,
    CHIP_TWO_STAGE_MAIXCAM_REMOTE_BINARY,
    DEFAULT_CONF,
    DEFAULT_INPUT_ADJUST_FILE,
    DEFAULT_NMS,
    DEFAULT_REMOTE_LOG,
    DEFAULT_SERIAL,
    default_adb_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "chip_roi" / "generated" / "gui_capture"
OBB_CALIBRATION_PROFILE = "chip-two-stage-obb-seg-imx678"
LATEST_DEFECT_SEG_REMOTE_MODEL = "model/chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft_split_int8.rknn"
OBB_CALIBRATION_PRESET = {
    "chip_conf": 0.45,
    "chip_interval": 1,
    "roi_smooth_alpha": 0.55,
    "roi_hold": 1,
}


@dataclass(slots=True)
class CameraSettings:
    backend: str = "adb"
    adb: str = default_adb_path()
    serial: str = DEFAULT_SERIAL
    profile: str = OBB_CALIBRATION_PROFILE
    remote_workdir: str = CHIP_REMOTE_WORKDIR
    remote_binary: str = CHIP_TWO_STAGE_MAIXCAM_REMOTE_BINARY
    remote_model: str = CHIP_ROI_OBB_REMOTE_MODEL
    remote_defect_model: str = LATEST_DEFECT_SEG_REMOTE_MODEL
    defect_model_kind: str = "seg"
    device: str = "/dev/video73"
    width: int = 1280
    height: int = 720
    fps: int = 30
    frames: int = 0
    skip: int = 3
    conf: float = DEFAULT_CONF
    chip_conf: float = OBB_CALIBRATION_PRESET["chip_conf"]
    defect_conf: float = 0.45
    roi_margin: float = 0.08
    roi_smooth_alpha: float = OBB_CALIBRATION_PRESET["roi_smooth_alpha"]
    roi_hold: int = OBB_CALIBRATION_PRESET["roi_hold"]
    chip_interval: int = OBB_CALIBRATION_PRESET["chip_interval"]
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
    input_adjust_file: str = DEFAULT_INPUT_ADJUST_FILE

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
    close_rgb: tuple[int, int, int] = (190, 255, 100)
    high_rgb: tuple[int, int, int] = (190, 255, 100)
    low_rgb: tuple[int, int, int] = (190, 255, 100)
    backlight_rgb: tuple[int, int, int] = (190, 255, 100)
    brightness: float = 0.50
    high_brightness: float = 0.20
    low_brightness: float = 0.20
    backlight_brightness: float = 0.20
    max_brightness: float = 0.80
    close_count: int = 8
    high_count: int = 12
    low_count: int = 24
    backlight_count: int = 256
    backlight_gpio: str = "GPIO3_A2"
    backlight_gpio_chip: str = "gpiochip3"
    backlight_gpio_line: int = 2
    backlight_enabled: bool = True
    count: int = 44
    device: str = "/dev/spidev1.0"

    def rgb_text(self) -> str:
        return ",".join(str(channel) for channel in self.close_rgb)

    def high_rgb_text(self) -> str:
        return ",".join(str(channel) for channel in self.high_rgb)

    def low_rgb_text(self) -> str:
        return ",".join(str(channel) for channel in self.low_rgb)

    def backlight_rgb_text(self) -> str:
        return ",".join(str(channel) for channel in self.backlight_rgb)

    def segment_counts_text(self) -> str:
        return f"{self.close_count},{self.high_count},{self.low_count}"

    def segment_brightness_text(self) -> str:
        return f"{self.brightness:.3f},{self.high_brightness:.3f},{self.low_brightness:.3f}"

    def segment_rgb_text(self) -> str:
        return ";".join((self.rgb_text(), self.high_rgb_text(), self.low_rgb_text()))

    def total_count(self) -> int:
        return self.close_count + self.high_count + self.low_count

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["rgb"] = list(self.rgb)
        data["close_rgb"] = list(self.close_rgb)
        data["high_rgb"] = list(self.high_rgb)
        data["low_rgb"] = list(self.low_rgb)
        data["backlight_rgb"] = list(self.backlight_rgb)
        data["segment_counts"] = [self.close_count, self.high_count, self.low_count]
        data["segment_brightness"] = [self.brightness, self.high_brightness, self.low_brightness]
        data["segment_rgb"] = [list(self.close_rgb), list(self.high_rgb), list(self.low_rgb)]
        return data


def apply_obb_calibration_preset(settings: CameraSettings) -> None:
    if settings.profile != OBB_CALIBRATION_PROFILE:
        return
    settings.chip_conf = OBB_CALIBRATION_PRESET["chip_conf"]
    settings.chip_interval = OBB_CALIBRATION_PRESET["chip_interval"]
    settings.roi_smooth_alpha = OBB_CALIBRATION_PRESET["roi_smooth_alpha"]
    settings.roi_hold = OBB_CALIBRATION_PRESET["roi_hold"]


def default_defect_model_for_profile(profile: str, defect_model_kind: str) -> str:
    if defect_model_kind == "seg" or "seg" in profile:
        return LATEST_DEFECT_SEG_REMOTE_MODEL
    return CHIP_REMOTE_MODEL

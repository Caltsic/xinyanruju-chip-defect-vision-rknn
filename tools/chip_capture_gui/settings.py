from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tools.adb_imx415_rknn_live_view import (
    CHIP_MAIXCAM_REMOTE_BINARY,
    CHIP_REMOTE_MODEL,
    CHIP_REMOTE_WORKDIR,
    DEFAULT_CONF,
    DEFAULT_NMS,
    DEFAULT_REMOTE_LOG,
    DEFAULT_SERIAL,
    default_adb_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "captures" / "gui_capture"


@dataclass(slots=True)
class CameraSettings:
    adb: str = default_adb_path()
    serial: str = DEFAULT_SERIAL
    remote_workdir: str = CHIP_REMOTE_WORKDIR
    remote_binary: str = CHIP_MAIXCAM_REMOTE_BINARY
    remote_model: str = CHIP_REMOTE_MODEL
    device: str = "/dev/video73"
    width: int = 1280
    height: int = 720
    fps: int = 30
    frames: int = 0
    skip: int = 3
    conf: float = DEFAULT_CONF
    nms: float = DEFAULT_NMS
    camera_format: str | None = "mjpg"
    roi: str | None = None
    remote_log: str = DEFAULT_REMOTE_LOG

    def to_namespace(self) -> SimpleNamespace:
        return SimpleNamespace(**asdict(self))


@dataclass(slots=True)
class ImageAdjustSettings:
    brightness: int = 0
    contrast: float = 1.0
    gamma: float = 1.0
    saturation: float = 1.0
    sharpness: float = 0.0
    denoise: int = 0
    clahe_enabled: bool = False
    clahe_clip_limit: float = 2.0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LightSettings:
    rgb: tuple[int, int, int] = (255, 255, 255)
    brightness: float = 0.08
    max_brightness: float = 0.30
    count: int = 8
    device: str = "/dev/spidev1.0"

    def rgb_text(self) -> str:
        return ",".join(str(channel) for channel in self.rgb)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["rgb"] = list(self.rgb)
        return data

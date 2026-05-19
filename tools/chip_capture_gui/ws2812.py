from __future__ import annotations

import shlex
import subprocess

from tools.adb_ws2812_ring import REMOTE_BACKLIGHT_HELPER, REMOTE_BACKLIGHT_SCRIPT, REMOTE_SCRIPT

from .settings import CameraSettings, LightSettings


def _clamp_brightness(value: float, maximum: float) -> float:
    return max(0.0, min(maximum, value))


def _spi_args(light_settings: LightSettings, off: bool) -> list[str]:
    remote_args = [
        "python3",
        REMOTE_SCRIPT,
        "--device",
        light_settings.device,
        "--count",
        str(light_settings.total_count()),
        "--segment-counts",
        light_settings.segment_counts_text(),
        "--segment-brightness",
        light_settings.segment_brightness_text(),
        "--segment-rgb",
        light_settings.segment_rgb_text(),
        "--brightness",
        f"{light_settings.brightness:.3f}",
    ]
    if off:
        remote_args.append("--off")
    else:
        remote_args.extend(["--rgb", light_settings.rgb_text()])
    return remote_args


def _backlight_args(light_settings: LightSettings, off: bool) -> list[str]:
    remote_args = [
        "python3",
        REMOTE_BACKLIGHT_SCRIPT,
        "--gpio",
        light_settings.backlight_gpio,
        "--chip",
        light_settings.backlight_gpio_chip,
        "--line",
        str(light_settings.backlight_gpio_line),
        "--count",
        str(light_settings.backlight_count),
        "--brightness",
        f"{light_settings.backlight_brightness:.3f}",
        "--helper",
        REMOTE_BACKLIGHT_HELPER,
    ]
    if off:
        remote_args.append("--off")
    else:
        remote_args.extend(["--rgb", light_settings.backlight_rgb_text()])
    return remote_args


def _join_outputs(*parts: str) -> str:
    return "\n".join(part for part in (part.strip() for part in parts) if part)


class AdbWs2812Controller:
    def __init__(self, camera_settings: CameraSettings, light_settings: LightSettings) -> None:
        self.camera_settings = camera_settings
        self.light_settings = light_settings

    def _adb_cmd(self, *parts: str) -> list[str]:
        command = [self.camera_settings.adb]
        if self.camera_settings.serial:
            command.extend(["-s", self.camera_settings.serial])
        command.extend(parts)
        return command

    def _shell(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self._adb_cmd("shell", script),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            check=False,
        )

    def _run_args(self, remote_args: list[str], label: str) -> str:
        result = self._shell(" ".join(shlex.quote(part) for part in remote_args))
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or f"{label} command failed")
        return result.stdout.strip()

    def _set_all(self, off: bool = False) -> str:
        spi_output = self._run_args(_spi_args(self.light_settings, off), "WS2812")
        if not self.light_settings.backlight_enabled:
            return spi_output
        backlight_output = self._run_args(_backlight_args(self.light_settings, off), "WS2812 backlight")
        return _join_outputs(spi_output, backlight_output)

    def set_brightness(self, brightness: float) -> str:
        brightness = _clamp_brightness(brightness, self.light_settings.max_brightness)
        self.light_settings.brightness = brightness
        return self._set_all()

    def set_brightnesses(self, close: float, high: float, low: float, backlight: float | None = None) -> str:
        max_brightness = self.light_settings.max_brightness
        self.light_settings.brightness = _clamp_brightness(close, max_brightness)
        self.light_settings.high_brightness = _clamp_brightness(high, max_brightness)
        self.light_settings.low_brightness = _clamp_brightness(low, max_brightness)
        if backlight is not None:
            self.light_settings.backlight_brightness = _clamp_brightness(backlight, max_brightness)
        return self._set_all()

    def apply(self) -> str:
        return self._set_all()

    def off(self) -> str:
        self.light_settings.brightness = 0.0
        self.light_settings.high_brightness = 0.0
        self.light_settings.low_brightness = 0.0
        self.light_settings.backlight_brightness = 0.0
        return self._set_all(off=True)


class LocalWs2812Controller:
    def __init__(self, _camera_settings: CameraSettings, light_settings: LightSettings) -> None:
        self.light_settings = light_settings

    def _run(self, remote_args: list[str]) -> str:
        result = subprocess.run(
            ["sh", "-c", " ".join(shlex.quote(part) for part in remote_args)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "WS2812 command failed")
        return result.stdout.strip()

    def _set_all(self, off: bool = False) -> str:
        spi_output = self._run(_spi_args(self.light_settings, off))
        if not self.light_settings.backlight_enabled:
            return spi_output
        backlight_output = self._run(_backlight_args(self.light_settings, off))
        return _join_outputs(spi_output, backlight_output)

    def set_brightness(self, brightness: float) -> str:
        brightness = _clamp_brightness(brightness, self.light_settings.max_brightness)
        self.light_settings.brightness = brightness
        return self._set_all()

    def set_brightnesses(self, close: float, high: float, low: float, backlight: float | None = None) -> str:
        max_brightness = self.light_settings.max_brightness
        self.light_settings.brightness = _clamp_brightness(close, max_brightness)
        self.light_settings.high_brightness = _clamp_brightness(high, max_brightness)
        self.light_settings.low_brightness = _clamp_brightness(low, max_brightness)
        if backlight is not None:
            self.light_settings.backlight_brightness = _clamp_brightness(backlight, max_brightness)
        return self._set_all()

    def apply(self) -> str:
        return self._set_all()

    def off(self) -> str:
        self.light_settings.brightness = 0.0
        self.light_settings.high_brightness = 0.0
        self.light_settings.low_brightness = 0.0
        self.light_settings.backlight_brightness = 0.0
        return self._set_all(off=True)


def create_ws2812_controller(camera_settings: CameraSettings, light_settings: LightSettings):
    if camera_settings.backend == "local":
        return LocalWs2812Controller(camera_settings, light_settings)
    if camera_settings.backend == "adb":
        return AdbWs2812Controller(camera_settings, light_settings)
    raise ValueError(f"unsupported camera backend: {camera_settings.backend}")

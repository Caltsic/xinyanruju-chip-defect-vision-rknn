from __future__ import annotations

import shlex
import subprocess

from tools.adb_ws2812_ring import REMOTE_SCRIPT

from .settings import CameraSettings, LightSettings


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

    def set_brightness(self, brightness: float) -> str:
        brightness = max(0.0, min(self.light_settings.max_brightness, brightness))
        self.light_settings.brightness = brightness
        remote_args = [
            "python3",
            REMOTE_SCRIPT,
            "--device",
            self.light_settings.device,
            "--count",
            str(self.light_settings.count),
            "--brightness",
            f"{brightness:.3f}",
            "--rgb",
            self.light_settings.rgb_text(),
        ]
        result = self._shell(" ".join(shlex.quote(part) for part in remote_args))
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "WS2812 command failed")
        return result.stdout.strip()

    def off(self) -> str:
        remote_args = [
            "python3",
            REMOTE_SCRIPT,
            "--device",
            self.light_settings.device,
            "--count",
            str(self.light_settings.count),
            "--brightness",
            "0",
            "--off",
        ]
        result = self._shell(" ".join(shlex.quote(part) for part in remote_args))
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "WS2812 off failed")
        self.light_settings.brightness = 0.0
        return result.stdout.strip()

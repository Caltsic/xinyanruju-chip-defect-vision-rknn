from __future__ import annotations

import subprocess
from pathlib import PurePosixPath

from tools.adb_imx415_rknn_live_view import (
    FpsMeter,
    ProtocolError,
    cleanup_remote_stream,
    focus_score,
    nv12_to_bgr,
    profile_defaults,
    read_stream_frame,
    start_adb_stream,
    stop_adb_process,
)

from .models import CameraFrame
from .settings import CameraSettings


class AdbRknnCamera:
    def __init__(self, settings: CameraSettings) -> None:
        self.settings = settings
        self.args = settings.to_namespace()
        self.class_names = list(profile_defaults(settings.profile)[3])
        self.process: subprocess.Popen[bytes] | None = None
        self._fps_meter = FpsMeter()
        self.frames_seen = 0
        self.last_stderr = ""

    def start(self) -> None:
        self.stop()
        self.process = start_adb_stream(self.args)
        self.frames_seen = 0
        self.last_stderr = ""

    def read_frame(self) -> CameraFrame | None:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("camera is not running")
        frame_info = read_stream_frame(self.process.stdout, self.settings.remote_log)
        if frame_info is None:
            return None
        clean_bgr = nv12_to_bgr(frame_info.payload, frame_info.width, frame_info.height)
        fps = self._fps_meter.tick()
        focus = focus_score(clean_bgr)
        self.frames_seen += 1
        return CameraFrame.from_parts(
            clean_bgr=clean_bgr,
            width=frame_info.width,
            height=frame_info.height,
            frame_index=frame_info.frame_index,
            detections=frame_info.detections,
            fps=fps,
            focus=focus,
        )

    def stop(self) -> None:
        if self.process is not None:
            self.last_stderr = stop_adb_process(self.process)
            self.process = None
        cleanup_remote_stream(self.args)

    def remote_log_tail(self, lines: int = 20) -> str:
        command = [self.settings.adb]
        if self.settings.serial:
            command.extend(["-s", self.settings.serial])
        command.extend(["shell", f"tail -n {int(lines)} {self.settings.remote_log} 2>/dev/null || true"])
        try:
            result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
        except Exception as exc:  # noqa: BLE001 - diagnostic path
            return str(exc)
        text = result.stdout.strip()
        if not text and result.stderr.strip():
            text = result.stderr.strip()
        return text

    def preflight(self) -> dict[str, bool]:
        binary_name = PurePosixPath(self.settings.remote_binary).name
        script = (
            f"test -e {self.settings.device}; echo camera=$?; "
            f"test -x {self.settings.remote_workdir}/{binary_name}; echo stream=$?; "
            "test -e /dev/spidev1.0; echo spidev=$?"
        )
        command = [self.settings.adb]
        if self.settings.serial:
            command.extend(["-s", self.settings.serial])
        command.extend(["shell", script])
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
        checks = {"camera": False, "stream": False, "spidev": False}
        for line in result.stdout.splitlines():
            if "=" not in line:
                continue
            key, value = line.strip().split("=", 1)
            if key in checks:
                checks[key] = value == "0"
        return checks


class CameraStreamError(RuntimeError):
    pass


def format_stream_error(camera: AdbRknnCamera, exc: BaseException | None = None) -> str:
    parts: list[str] = []
    if exc is not None and not isinstance(exc, ProtocolError):
        parts.append(str(exc))
    elif exc is not None:
        parts.append(str(exc))
    if camera.last_stderr.strip():
        parts.append(camera.last_stderr.strip())
    log_tail = camera.remote_log_tail()
    if log_tail:
        parts.append(log_tail)
    return "\n".join(part for part in parts if part).strip()

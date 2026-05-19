from __future__ import annotations

import json
import math
import os
import shlex
import signal
import struct
import subprocess
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


StatusCallback = Callable[[str], None]


def _default_work_dir() -> Path:
    if os.name == "nt":
        return Path.cwd() / "tmp" / "voice_assistant"
    return Path("/userdata/chipcheck_vision/voice_assistant")


@dataclass(slots=True)
class VoiceAssistantSettings:
    enabled: bool = False
    work_dir: Path = _default_work_dir()
    record_device: str = "hw:0,0"
    playback_device: str = "plughw:0,0"
    sample_rate: int = 16000
    channels: int = 1
    sample_format: str = "S16_LE"
    assistant_command: str = ""
    command_timeout_sec: int = 360
    max_threads: int = 2
    reply_display_sec: float = 28.0


def default_minimind_command() -> str:
    if os.name == "nt":
        return ""
    python_path = Path("/srv/rk3576-storage/minimind_o_env/bin/python")
    runner_path = Path("/userdata/chipcheck_vision/tools/minimind_o_voice_runner.py")
    repo_path = Path("/mnt/eaget/workspace/minimind-o")
    if not python_path.exists() or not runner_path.exists() or not repo_path.exists():
        return ""
    return (
        f"{shlex.quote(str(python_path))} {shlex.quote(str(runner_path))} "
        f"--repo {shlex.quote(str(repo_path))} "
        "--input-wav {input_wav} --reply-wav {reply_wav} "
        "--result-json {result_json} --stream-text {stream_text} "
        "--mode audio --max-new-tokens 12 --threads 2 --device cpu --fallback-tone 1"
    )


class VoiceAssistantController:
    def __init__(
        self,
        settings: VoiceAssistantSettings | None = None,
        status_callback: StatusCallback | None = None,
    ) -> None:
        self.settings = settings or VoiceAssistantSettings()
        if self.settings.enabled and not self.settings.assistant_command.strip():
            self.settings.assistant_command = default_minimind_command()
        self._status_callback = status_callback
        self._lock = threading.Lock()
        self._record_proc: subprocess.Popen | None = None
        self._record_log = None
        self._worker: threading.Thread | None = None
        self._state = "disabled" if not self.settings.enabled else "idle"
        self.last_message = self._state
        self._reply_text = ""
        self._reply_visible_until = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def is_recording(self) -> bool:
        return self.state == "recording"

    @property
    def is_busy(self) -> bool:
        return self.state in {"recording", "thinking", "playing"}

    def snapshot_status(self) -> str:
        with self._lock:
            return self.last_message

    def snapshot_reply_text(self) -> str:
        with self._lock:
            if not self._reply_text:
                return ""
            if self._state in {"thinking", "playing"} or time.time() <= self._reply_visible_until:
                return self._reply_text
            return ""

    def toggle_recording(self) -> str:
        if self.is_recording:
            return self.stop_recording()
        return self.start_recording()

    def start_recording(self) -> str:
        if not self.settings.enabled:
            return self._set_status("voice disabled")
        with self._lock:
            if self._state != "idle":
                return self.last_message
            self.settings.work_dir.mkdir(parents=True, exist_ok=True)
            input_wav = self.input_wav
            try:
                input_wav.unlink(missing_ok=True)
            except OSError:
                pass
            log_path = self.settings.work_dir / "arecord.log"
            self._record_log = log_path.open("ab")
            command = [
                "arecord",
                "-D",
                self.settings.record_device,
                "-f",
                self.settings.sample_format,
                "-r",
                str(self.settings.sample_rate),
                "-c",
                str(self.settings.channels),
                "-t",
                "wav",
                str(input_wav),
            ]
            try:
                self._record_proc = subprocess.Popen(
                    command,
                    stdout=self._record_log,
                    stderr=subprocess.STDOUT,
                    start_new_session=(os.name != "nt"),
                )
            except Exception as exc:  # noqa: BLE001
                self._close_record_log()
                self._record_proc = None
                self._state = "idle"
                return self._set_status(f"voice record failed: {exc}")
            self._state = "recording"
        return self._set_status("voice recording")

    def stop_recording(self, run_assistant: bool = True) -> str:
        with self._lock:
            proc = self._record_proc
            if self._state != "recording" or proc is None:
                return self.last_message
        self._stop_record_process(proc)
        self._close_record_log()
        with self._lock:
            self._record_proc = None
        if not self.input_wav.exists() or self.input_wav.stat().st_size <= 44:
            with self._lock:
                self._state = "idle"
            return self._set_status("voice ignored: empty recording")
        if not run_assistant:
            with self._lock:
                self._state = "idle"
            return self._set_status("voice stopped")
        with self._lock:
            self._state = "thinking"
            self._worker = threading.Thread(target=self._run_assistant_pipeline, daemon=True)
            self._worker.start()
        return self._set_status("voice thinking")

    def play_last_reply(self) -> str:
        if not self.settings.enabled:
            return self._set_status("voice disabled")
        if not self.reply_wav.exists():
            return self._set_status("voice no reply")
        with self._lock:
            if self._state != "idle":
                return self.last_message
            self._state = "playing"
            self._worker = threading.Thread(target=self._play_only, daemon=True)
            self._worker.start()
        return self._set_status("voice playing")

    def shutdown(self) -> None:
        with self._lock:
            proc = self._record_proc
            self._record_proc = None
        if proc is not None:
            self._stop_record_process(proc)
        self._close_record_log()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=1.0)
        with self._lock:
            if self.settings.enabled:
                self._state = "idle"

    @property
    def input_wav(self) -> Path:
        return self.settings.work_dir / "last_input.wav"

    @property
    def reply_wav(self) -> Path:
        return self.settings.work_dir / "last_reply.wav"

    @property
    def result_json(self) -> Path:
        return self.settings.work_dir / "last_result.json"

    @property
    def stream_text(self) -> Path:
        return self.settings.work_dir / "last_reply_stream.txt"

    def _run_assistant_pipeline(self) -> None:
        try:
            self._set_status("voice thinking")
            self._prepare_outputs()
            if self.settings.assistant_command.strip():
                self._run_assistant_command()
            else:
                self._write_placeholder_result()
            self._set_state("playing")
            self._play_reply()
            self._set_state("idle")
            self._set_status("voice done")
        except Exception as exc:  # noqa: BLE001
            self._set_reply_text(f"MiniMind failed: {exc}", active=False)
            self._set_state("idle")
            self._set_status(f"voice failed: {exc}")

    def _play_only(self) -> None:
        try:
            self._play_reply()
            self._set_state("idle")
            self._set_status("voice replay done")
        except Exception as exc:  # noqa: BLE001
            self._set_state("idle")
            self._set_status(f"voice replay failed: {exc}")

    def _run_assistant_command(self) -> None:
        command = self.settings.assistant_command.format(
            input_wav=str(self.input_wav),
            reply_wav=str(self.reply_wav),
            result_json=str(self.result_json),
            work_dir=str(self.settings.work_dir),
            stream_text=str(self.stream_text),
        )
        env = os.environ.copy()
        thread_count = str(max(1, self.settings.max_threads))
        env.setdefault("OMP_NUM_THREADS", thread_count)
        env.setdefault("OPENBLAS_NUM_THREADS", thread_count)
        env.setdefault("MKL_NUM_THREADS", thread_count)
        env.setdefault("NUMEXPR_NUM_THREADS", thread_count)
        log_path = self.settings.work_dir / "assistant_command.log"
        with log_path.open("ab") as log_file:
            log_file.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n".encode("utf-8"))
            log_file.write((command + "\n").encode("utf-8", errors="replace"))
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=self.settings.work_dir,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=(os.name != "nt"),
            )
            deadline = time.time() + self.settings.command_timeout_sec
            while proc.poll() is None:
                self._poll_reply_stream(active=True)
                if time.time() > deadline:
                    self._stop_record_process(proc)
                    raise TimeoutError(f"assistant command timed out after {self.settings.command_timeout_sec}s")
                time.sleep(0.25)
            self._poll_reply_stream(active=True)
        if proc.returncode != 0:
            raise RuntimeError(f"assistant command exited {proc.returncode}")
        self._load_result_reply_text()
        if not self.reply_wav.exists():
            self._generate_tone(self.reply_wav)

    def _write_placeholder_result(self) -> None:
        payload = {
            "mode": "placeholder",
            "input_wav": str(self.input_wav),
            "reply_wav": str(self.reply_wav),
            "reply_text": "MiniMind-O command is not configured yet. Audio capture and playback are ready.",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.result_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._set_reply_text(payload["reply_text"], active=False)
        self._generate_tone(self.reply_wav)

    def _prepare_outputs(self) -> None:
        for path in (self.reply_wav, self.result_json, self.stream_text):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self._set_reply_text("", active=False)

    def _poll_reply_stream(self, active: bool) -> None:
        try:
            text = self.stream_text.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if text:
            self._set_reply_text(text, active=active)

    def _load_result_reply_text(self) -> None:
        try:
            payload = json.loads(self.result_json.read_text(encoding="utf-8"))
        except Exception:
            self._poll_reply_stream(active=False)
            return
        text = str(payload.get("reply_text") or "").strip()
        if text:
            self._set_reply_text(text, active=False)

    def _set_reply_text(self, text: str, active: bool) -> None:
        with self._lock:
            self._reply_text = text
            if text:
                self._reply_visible_until = time.time() + max(1.0, self.settings.reply_display_sec)
            elif not active:
                self._reply_visible_until = 0.0

    def _play_reply(self) -> None:
        if not self.reply_wav.exists():
            raise RuntimeError("reply wav missing")
        command = ["aplay", "-D", self.settings.playback_device, str(self.reply_wav)]
        log_path = self.settings.work_dir / "aplay.log"
        with log_path.open("ab") as log_file:
            result = subprocess.run(command, stdout=log_file, stderr=subprocess.STDOUT, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"aplay exited {result.returncode}")

    def _generate_tone(self, path: Path, duration_sec: float = 0.28, frequency: float = 880.0) -> None:
        sample_rate = 16000
        amplitude = 0.25
        frame_count = int(sample_rate * duration_sec)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for index in range(frame_count):
                window = math.sin(math.pi * min(1.0, index / max(1, frame_count - 1)))
                sample = int(32767 * amplitude * window * math.sin(2 * math.pi * frequency * index / sample_rate))
                wav.writeframes(struct.pack("<h", sample))

    def _stop_record_process(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(proc.pid, signal.SIGINT)
            else:
                proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.0)
            except Exception:
                pass

    def _close_record_log(self) -> None:
        if self._record_log is not None:
            try:
                self._record_log.close()
            except Exception:
                pass
            self._record_log = None

    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state

    def _set_status(self, message: str) -> str:
        with self._lock:
            self.last_message = message
        if self._status_callback is not None:
            self._status_callback(message)
        return message


def shell_quote_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)

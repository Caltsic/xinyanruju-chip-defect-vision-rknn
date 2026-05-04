from __future__ import annotations

import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import cv2
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QCloseEvent, QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tools.adb_imx415_rknn_live_view import CHIP_DEFECT_CLASSES, draw_detections

from .camera import AdbRknnCamera, format_stream_error
from .image_adjust import apply_adjustments
from .models import CameraFrame
from .settings import DEFAULT_OUTPUT_DIR, CameraSettings, ImageAdjustSettings, LightSettings
from .storage import CaptureStorage
from .ws2812 import AdbWs2812Controller


NO_FRAME_TIMEOUT_MS = 8000


class CameraThread(QThread):
    frame_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    error_changed = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, settings: CameraSettings) -> None:
        super().__init__()
        self.settings = settings
        self._running = False
        self._camera: AdbRknnCamera | None = None

    def run(self) -> None:
        camera = AdbRknnCamera(self.settings)
        self._camera = camera
        self._running = True
        try:
            self.status_changed.emit("starting")
            checks = camera.preflight()
            missing_required = [name for name in ("camera", "stream") if not checks.get(name)]
            if missing_required:
                self.error_changed.emit(f"preflight failed: {', '.join(missing_required)}")
                return
            if not checks.get("spidev"):
                self.status_changed.emit("spidev missing")
            camera.start()
            self.status_changed.emit("running")
            while self._running:
                frame = camera.read_frame()
                if frame is None:
                    if camera.frames_seen == 0:
                        message = format_stream_error(camera) or "no frames"
                        self.error_changed.emit(message)
                    break
                self.frame_ready.emit(frame)
        except Exception as exc:  # noqa: BLE001 - surface diagnostics to GUI
            self.error_changed.emit(format_stream_error(camera, exc) or str(exc))
        finally:
            camera.stop()
            self._camera = None
            self._running = False
            self.stopped.emit()

    def stop(self) -> None:
        self._running = False
        if self._camera is not None:
            self._camera.stop()


class SliderRow(QWidget):
    value_changed = pyqtSignal()

    def __init__(
        self,
        name: str,
        minimum: int,
        maximum: int,
        value: int,
        formatter,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.formatter = formatter
        self.label = QLabel(name)
        self.value_label = QLabel("")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._update_value)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.addWidget(self.label, 0, 0)
        layout.addWidget(self.value_label, 0, 1)
        layout.addWidget(self.slider, 1, 0, 1, 2)
        self._update_value()

    def value(self) -> int:
        return int(self.slider.value())

    def set_value(self, value: int) -> None:
        self.slider.setValue(value)

    def _update_value(self) -> None:
        self.value_label.setText(str(self.formatter(self.value())))
        self.value_changed.emit()


class MainWindow(QMainWindow):
    light_error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.camera_settings = CameraSettings()
        self.image_settings = ImageAdjustSettings()
        self.light_settings = LightSettings()
        self.storage = CaptureStorage(DEFAULT_OUTPUT_DIR)
        self.light_controller = AdbWs2812Controller(self.camera_settings, self.light_settings)
        self.light_executor = ThreadPoolExecutor(max_workers=1)

        self.camera_thread: CameraThread | None = None
        self.last_frame: CameraFrame | None = None
        self.last_clean_bgr = None
        self.last_annotated_bgr = None
        self.last_drawn_count = 0
        self.last_frame_time = 0.0
        self.current_pixmap: QPixmap | None = None
        self.light_future: Future | None = None
        self.class_names = list(CHIP_DEFECT_CLASSES)

        self.no_frame_timer = QTimer(self)
        self.no_frame_timer.setSingleShot(True)
        self.no_frame_timer.timeout.connect(self._handle_no_frame_timeout)
        self.light_timer = QTimer(self)
        self.light_timer.setSingleShot(True)
        self.light_timer.timeout.connect(self._send_light)
        self.light_error.connect(lambda message: self._set_status(f"light failed: {message}"))

        self._build_ui()
        self._apply_style()
        self._set_status("ready")

    def _build_ui(self) -> None:
        self.setWindowTitle("Chip Capture")
        self.resize(1220, 760)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.preview = QLabel("No Signal")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(720, 480)
        self.preview.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.preview, stretch=1)

        panel = QWidget()
        panel.setFixedWidth(320)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(10)

        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.start_btn.clicked.connect(self.start_camera)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_btn.clicked.connect(self.stop_camera)
        self.stop_btn.setEnabled(False)
        top_row = QHBoxLayout()
        top_row.addWidget(self.start_btn)
        top_row.addWidget(self.stop_btn)
        panel_layout.addLayout(top_row)

        self.capture_btn = QPushButton("Capture")
        self.capture_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.capture_btn.setEnabled(False)
        self.capture_btn.clicked.connect(self.capture)
        panel_layout.addWidget(self.capture_btn)

        folder_row = QHBoxLayout()
        self.folder_label = QLabel(str(DEFAULT_OUTPUT_DIR))
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_btn = QPushButton("Folder")
        self.folder_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.folder_btn.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder_label, stretch=1)
        folder_row.addWidget(self.folder_btn)
        panel_layout.addLayout(folder_row)

        self.light_row = SliderRow("Light", 0, int(self.light_settings.max_brightness * 100), 8, lambda value: f"{value}%")
        self.light_row.value_changed.connect(self._schedule_light)
        panel_layout.addWidget(self.light_row)

        self.advanced_btn = QToolButton()
        self.advanced_btn.setText("Advanced")
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setChecked(False)
        self.advanced_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_btn.clicked.connect(self._toggle_advanced)
        panel_layout.addWidget(self.advanced_btn)

        self.advanced_panel = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)
        self.brightness_row = SliderRow("Brightness", -100, 100, 0, lambda value: f"{value:+d}")
        self.contrast_row = SliderRow("Contrast", 0, 300, 100, lambda value: f"{value / 100:.2f}")
        self.gamma_row = SliderRow("Gamma", 20, 300, 100, lambda value: f"{value / 100:.2f}")
        self.saturation_row = SliderRow("Saturation", 0, 300, 100, lambda value: f"{value / 100:.2f}")
        self.sharpness_row = SliderRow("Sharpness", 0, 300, 0, lambda value: f"{value / 100:.2f}")
        self.denoise_row = SliderRow("Denoise", 0, 30, 0, lambda value: str(value))
        self.clahe_check = QCheckBox("CLAHE")
        self.clahe_row = SliderRow("CLAHE Clip", 10, 60, 20, lambda value: f"{value / 10:.1f}")
        for row in (
            self.brightness_row,
            self.contrast_row,
            self.gamma_row,
            self.saturation_row,
            self.sharpness_row,
            self.denoise_row,
            self.clahe_row,
        ):
            row.value_changed.connect(self._image_settings_changed)
            advanced_layout.addWidget(row)
        self.clahe_check.toggled.connect(self._image_settings_changed)
        advanced_layout.insertWidget(6, self.clahe_check)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self.reset_adjustments)
        advanced_layout.addWidget(reset_btn)
        self.advanced_panel.setVisible(False)
        panel_layout.addWidget(self.advanced_panel)

        self.status_label = QLabel("ready")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        panel_layout.addStretch(1)
        panel_layout.addWidget(self.status_label)

        root.addWidget(panel)
        self.setCentralWidget(central)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #111315; color: #e8e8e8; font-size: 13px; }
            QLabel { color: #d7d7d7; }
            QLabel#statusLabel { color: #aeb4ba; padding: 8px 2px; }
            QPushButton, QToolButton {
                background: #24282c;
                border: 1px solid #3a4046;
                border-radius: 6px;
                padding: 8px 10px;
                color: #f2f2f2;
            }
            QPushButton:hover, QToolButton:hover { background: #2e343a; }
            QPushButton:disabled { color: #697078; background: #1a1d20; border-color: #272b30; }
            QSlider::groove:horizontal { height: 4px; background: #30363c; border-radius: 2px; }
            QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: #e5e7eb; }
            QCheckBox { spacing: 8px; }
            """
        )
        self.preview.setStyleSheet("background: #050607; color: #59616a; border-radius: 6px;")

    def start_camera(self) -> None:
        if self.camera_thread is not None:
            return
        self.last_frame = None
        self.last_clean_bgr = None
        self.last_annotated_bgr = None
        self.last_frame_time = 0.0
        self.capture_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._send_light()
        self.camera_thread = CameraThread(self.camera_settings)
        self.camera_thread.frame_ready.connect(self._on_frame)
        self.camera_thread.status_changed.connect(self._set_status)
        self.camera_thread.error_changed.connect(self._on_camera_error)
        self.camera_thread.stopped.connect(self._on_camera_stopped)
        self.camera_thread.start()
        self.no_frame_timer.start(NO_FRAME_TIMEOUT_MS)

    def stop_camera(self) -> None:
        thread = self.camera_thread
        if thread is not None:
            thread.stop()
            if not thread.wait(5000):
                thread.terminate()
                thread.wait(2000)
        self.no_frame_timer.stop()

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Folder", str(self.storage.output_dir))
        if not selected:
            return
        output_dir = Path(selected)
        self.storage.set_output_dir(output_dir)
        self.folder_label.setText(str(output_dir))

    def capture(self) -> None:
        if self.last_frame is None or self.last_clean_bgr is None or self.last_annotated_bgr is None:
            return
        try:
            clean_path, annotated_path, _ = self.storage.save(
                frame=self.last_frame,
                clean_bgr=self.last_clean_bgr,
                annotated_bgr=self.last_annotated_bgr,
                camera_settings=self.camera_settings,
                image_settings=self.image_settings,
                light_settings=self.light_settings,
                drawn_count=self.last_drawn_count,
            )
        except Exception as exc:  # noqa: BLE001 - surface capture failures
            self._set_status(f"save failed: {exc}")
            return
        self._set_status(f"saved: {clean_path.name} | {annotated_path.name}")

    def reset_adjustments(self) -> None:
        self.brightness_row.set_value(0)
        self.contrast_row.set_value(100)
        self.gamma_row.set_value(100)
        self.saturation_row.set_value(100)
        self.sharpness_row.set_value(0)
        self.denoise_row.set_value(0)
        self.clahe_check.setChecked(False)
        self.clahe_row.set_value(20)
        self._image_settings_changed()

    def _toggle_advanced(self) -> None:
        visible = self.advanced_btn.isChecked()
        self.advanced_btn.setArrowType(Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)
        self.advanced_panel.setVisible(visible)

    def _image_settings_changed(self) -> None:
        self.image_settings = ImageAdjustSettings(
            brightness=self.brightness_row.value(),
            contrast=self.contrast_row.value() / 100,
            gamma=self.gamma_row.value() / 100,
            saturation=self.saturation_row.value() / 100,
            sharpness=self.sharpness_row.value() / 100,
            denoise=self.denoise_row.value(),
            clahe_enabled=self.clahe_check.isChecked(),
            clahe_clip_limit=self.clahe_row.value() / 10,
        )
        if self.last_frame is not None:
            self._render_frame(self.last_frame)

    def _schedule_light(self) -> None:
        self.light_timer.start(180)

    def _send_light(self) -> None:
        brightness = self.light_row.value() / 100
        self.light_settings.brightness = brightness
        self.light_future = self.light_executor.submit(self.light_controller.set_brightness, brightness)
        self.light_future.add_done_callback(self._light_done)

    def _light_done(self, future: Future) -> None:
        try:
            future.result()
        except Exception as exc:  # noqa: BLE001 - concise GUI status
            self.light_error.emit(str(exc))

    def _handle_no_frame_timeout(self) -> None:
        if self.last_frame_time > 0 and time.perf_counter() - self.last_frame_time < NO_FRAME_TIMEOUT_MS / 1000:
            return
        self._set_status("no frames")
        self.stop_camera()

    def _on_frame(self, frame: CameraFrame) -> None:
        self.last_frame_time = time.perf_counter()
        self.no_frame_timer.stop()
        self.capture_btn.setEnabled(True)
        self._render_frame(frame)

    def _render_frame(self, frame: CameraFrame) -> None:
        self.last_frame = frame
        self.last_clean_bgr = frame.clean_bgr.copy()
        preview_bgr = apply_adjustments(frame.clean_bgr, self.image_settings)
        annotated_bgr = preview_bgr.copy()
        self.last_drawn_count = draw_detections(annotated_bgr, frame.detections, self.class_names)
        self.last_annotated_bgr = annotated_bgr
        self._set_preview_image(annotated_bgr)
        self._set_status(
            f"fps {frame.fps:.1f} | focus {frame.focus:.0f} | det {len(frame.detections)}/{self.last_drawn_count} | frame {frame.frame_index}"
        )

    def _set_preview_image(self, bgr_image) -> None:
        rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888).copy()
        self.current_pixmap = QPixmap.fromImage(image)
        self._rescale_preview()

    def _rescale_preview(self) -> None:
        if self.current_pixmap is None:
            return
        scaled = self.current_pixmap.scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(scaled)

    def _on_camera_error(self, message: str) -> None:
        summary = self._error_summary(message)
        self._set_status(f"camera failed: {summary}")

    def _on_camera_stopped(self) -> None:
        self.no_frame_timer.stop()
        self.camera_thread = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self.last_frame is None:
            self.capture_btn.setEnabled(False)
        if self.status_label.text() in ("running", "starting"):
            self._set_status("stopped")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _error_summary(self, message: str) -> str:
        lines = [line.strip() for line in message.splitlines() if line.strip()]
        if not lines:
            return "unknown"
        keywords = ("failed", "error", "timeout", "invalid", "short", "bad magic", "no frames")
        for line in reversed(lines):
            lowered = line.lower()
            if any(keyword in lowered for keyword in keywords):
                return line
        return lines[-1]

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._rescale_preview()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.stop_camera()
        try:
            self.light_executor.submit(self.light_controller.off).result(timeout=2)
        except Exception:
            pass
        self.light_executor.shutdown(wait=False, cancel_futures=True)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()

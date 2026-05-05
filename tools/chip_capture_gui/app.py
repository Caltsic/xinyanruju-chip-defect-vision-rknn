from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import cv2
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QCloseEvent, QImage, QKeyEvent, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tools.chip_roi_utils import clamp_box, draw_chip_box, expand_box, locate_chip_dark_edge
from tools.adb_imx415_rknn_live_view import (
    CHIP_DEFECT_SEG_REMOTE_MODEL,
    CHIP_REMOTE_MODEL,
    CHIP_TWO_STAGE_CLASSES,
    TWO_STAGE_PROFILES,
    draw_detections,
    filter_display_detections,
)

from .camera import RknnCamera, create_camera, format_stream_error, write_input_adjust_config
from .image_adjust import apply_adjustments
from .models import CameraFrame
from .settings import DEFAULT_OUTPUT_DIR, CameraSettings, ImageAdjustSettings, LightSettings
from .storage import CaptureStorage, ChipRoiRecord
from .ws2812 import create_ws2812_controller


NO_FRAME_TIMEOUT_MS = 8000


@dataclass(slots=True)
class RoiReviewState:
    record: ChipRoiRecord
    clean_bgr: object
    box: tuple[int, int, int, int] | None
    capture_adjusted: bool


class CameraThread(QThread):
    frame_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    error_changed = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, settings: CameraSettings) -> None:
        super().__init__()
        self.settings = settings
        self._running = False
        self._camera: RknnCamera | None = None

    def run(self) -> None:
        camera = create_camera(self.settings)
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
        self.light_controller = create_ws2812_controller(self.camera_settings, self.light_settings)
        self.light_executor = ThreadPoolExecutor(max_workers=1)
        self.adjust_executor = ThreadPoolExecutor(max_workers=1)

        self.camera_thread: CameraThread | None = None
        self.last_frame: CameraFrame | None = None
        self.last_clean_bgr = None
        self.last_annotated_bgr = None
        self.last_drawn_count = 0
        self.last_frame_time = 0.0
        self.current_pixmap: QPixmap | None = None
        self.light_future: Future | None = None
        self.class_names = list(CHIP_TWO_STAGE_CLASSES)
        self.review_state: RoiReviewState | None = None
        self.roi_tune_buttons: list[QPushButton] = []
        self.mode_group: QButtonGroup | None = None
        self.live_overlay_enabled = True
        self._shutting_down = False

        self.no_frame_timer = QTimer(self)
        self.no_frame_timer.setSingleShot(True)
        self.no_frame_timer.timeout.connect(self._handle_no_frame_timeout)
        self.light_timer = QTimer(self)
        self.light_timer.setSingleShot(True)
        self.light_timer.timeout.connect(self._send_light)
        self.adjust_timer = QTimer(self)
        self.adjust_timer.setSingleShot(True)
        self.adjust_timer.timeout.connect(self._send_input_adjust)
        self.light_error.connect(lambda message: self._set_status(f"light failed: {message}"))

        self._build_ui()
        self._apply_style()
        self._set_status("ready")

    def _build_ui(self) -> None:
        self.setWindowTitle("Mint Chip ROI Studio")
        self.resize(1320, 820)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        self.preview = QLabel("No Signal")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(780, 520)
        self.preview.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.preview, stretch=1)

        panel = QWidget()
        panel.setObjectName("sidePanel")
        panel.setFixedWidth(380)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(12)

        title = QLabel("MINT CHIP ROI")
        title.setObjectName("titleLabel")
        subtitle = QLabel("capture · auto box · quick review")
        subtitle.setObjectName("subtitleLabel")
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)

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

        mode_box = QGroupBox("Mode")
        mode_layout = QGridLayout(mode_box)
        self.capture_mode_btn = QPushButton("Capture / Label")
        self.capture_mode_btn.setCheckable(True)
        self.capture_mode_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.live_mode_btn = QPushButton("Live Detect")
        self.live_mode_btn.setCheckable(True)
        self.live_mode_btn.setChecked(True)
        self.live_mode_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.capture_mode_btn, 0)
        self.mode_group.addButton(self.live_mode_btn, 1)
        self.mode_group.idClicked.connect(self._mode_changed)
        self.draw_detections_check = QCheckBox("Draw detection masks/boxes")
        self.draw_detections_check.setChecked(True)
        self.draw_detections_check.toggled.connect(self._live_overlay_changed)
        self.seg_model_check = QCheckBox("Use segmentation defect model")
        self.seg_model_check.setChecked(self.camera_settings.defect_model_kind == "seg")
        self.seg_model_check.toggled.connect(self._seg_model_toggled)
        self.input_adjust_check = QCheckBox("Sync view to NPU input")
        self.input_adjust_check.setChecked(self.camera_settings.input_adjust)
        self.input_adjust_check.toggled.connect(self._input_adjust_toggled)
        self.save_adjusted_check = QCheckBox("Save adjusted capture")
        self.save_adjusted_check.setChecked(True)
        mode_layout.addWidget(self.capture_mode_btn, 0, 0)
        mode_layout.addWidget(self.live_mode_btn, 0, 1)
        mode_layout.addWidget(self.draw_detections_check, 1, 0, 1, 2)
        mode_layout.addWidget(self.seg_model_check, 2, 0, 1, 2)
        mode_layout.addWidget(self.input_adjust_check, 3, 0, 1, 2)
        mode_layout.addWidget(self.save_adjusted_check, 4, 0, 1, 2)
        panel_layout.addWidget(mode_box)

        batch_box = QGroupBox("Batch")
        batch_layout = QGridLayout(batch_box)
        batch_layout.setColumnStretch(1, 1)
        self.prefix_edit = QLineEdit("chip")
        self.prefix_edit.setMaxLength(32)
        self.prefix_edit.textChanged.connect(self._update_next_name)
        self.next_name_label = QLabel("")
        self.next_name_label.setObjectName("monoLabel")
        batch_layout.addWidget(QLabel("Prefix"), 0, 0)
        batch_layout.addWidget(self.prefix_edit, 0, 1)
        batch_layout.addWidget(QLabel("Next"), 1, 0)
        batch_layout.addWidget(self.next_name_label, 1, 1)
        panel_layout.addWidget(batch_box)

        folder_box = QGroupBox("Output")
        folder_layout = QVBoxLayout(folder_box)
        self.folder_label = QLabel(str(DEFAULT_OUTPUT_DIR))
        self.folder_label.setObjectName("pathLabel")
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_btn = QPushButton("Choose Batch Folder")
        self.folder_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.folder_btn.clicked.connect(self.choose_folder)
        folder_layout.addWidget(self.folder_label)
        folder_layout.addWidget(self.folder_btn)
        panel_layout.addWidget(folder_box)

        self.capture_btn = QPushButton("Capture ROI")
        self.capture_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.capture_btn.setEnabled(False)
        self.capture_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.capture_btn.clicked.connect(self.capture)
        panel_layout.addWidget(self.capture_btn)

        review_row = QHBoxLayout()
        self.accept_btn = QPushButton("Accept")
        self.accept_btn.setEnabled(False)
        self.accept_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.accept_btn.clicked.connect(self.accept_roi)
        self.negative_btn = QPushButton("Negative")
        self.negative_btn.setEnabled(False)
        self.negative_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.negative_btn.clicked.connect(self.mark_negative)
        review_row.addWidget(self.accept_btn)
        review_row.addWidget(self.negative_btn)
        panel_layout.addLayout(review_row)

        self.review_hint_label = QLabel("Capture a frame to enter ROI review.")
        self.review_hint_label.setObjectName("reviewHintLabel")
        self.review_hint_label.setWordWrap(True)
        panel_layout.addWidget(self.review_hint_label)

        roi_box = QGroupBox("ROI Tuning")
        roi_layout = QGridLayout(roi_box)
        self.step_spin = QSpinBox()
        self.step_spin.setRange(1, 80)
        self.step_spin.setValue(4)
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.001, 0.10)
        self.scale_spin.setSingleStep(0.001)
        self.scale_spin.setDecimals(3)
        self.scale_spin.setValue(0.005)
        roi_layout.addWidget(QLabel("Move px"), 0, 0)
        roi_layout.addWidget(self.step_spin, 0, 1)
        roi_layout.addWidget(QLabel("Scale"), 0, 2)
        roi_layout.addWidget(self.scale_spin, 0, 3)
        up_btn = QPushButton("W")
        left_btn = QPushButton("A")
        down_btn = QPushButton("S")
        right_btn = QPushButton("D")
        plus_btn = QPushButton("+")
        minus_btn = QPushButton("-")
        self.roi_tune_buttons = [up_btn, down_btn, left_btn, right_btn, plus_btn, minus_btn]
        for button in self.roi_tune_buttons:
            button.setEnabled(False)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        up_btn.clicked.connect(lambda: self.adjust_roi(0, -self.step_spin.value()))
        down_btn.clicked.connect(lambda: self.adjust_roi(0, self.step_spin.value()))
        left_btn.clicked.connect(lambda: self.adjust_roi(-self.step_spin.value(), 0))
        right_btn.clicked.connect(lambda: self.adjust_roi(self.step_spin.value(), 0))
        plus_btn.clicked.connect(lambda: self.scale_roi(float(self.scale_spin.value())))
        minus_btn.clicked.connect(lambda: self.scale_roi(-float(self.scale_spin.value())))
        roi_layout.addWidget(up_btn, 1, 1)
        roi_layout.addWidget(left_btn, 2, 0)
        roi_layout.addWidget(down_btn, 2, 1)
        roi_layout.addWidget(right_btn, 2, 2)
        roi_layout.addWidget(minus_btn, 1, 3)
        roi_layout.addWidget(plus_btn, 2, 3)
        panel_layout.addWidget(roi_box)

        self.light_row = SliderRow(
            "Light",
            0,
            int(self.light_settings.max_brightness * 100),
            int(round(self.light_settings.brightness * 100)),
            lambda value: f"{value}%",
        )
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
        adjust = self.image_settings
        self.brightness_row = SliderRow("Brightness", -100, 100, adjust.brightness, lambda value: f"{value:+d}")
        self.contrast_row = SliderRow("Contrast", 0, 300, int(round(adjust.contrast * 100)), lambda value: f"{value / 100:.2f}")
        self.gamma_row = SliderRow("Gamma", 20, 300, int(round(adjust.gamma * 100)), lambda value: f"{value / 100:.2f}")
        self.saturation_row = SliderRow("Saturation", 0, 300, int(round(adjust.saturation * 100)), lambda value: f"{value / 100:.2f}")
        self.sharpness_row = SliderRow("Sharpness", 0, 300, int(round(adjust.sharpness * 100)), lambda value: f"{value / 100:.2f}")
        self.denoise_row = SliderRow("Denoise", 0, 30, adjust.denoise, lambda value: str(value))
        self.denoise_row.slider.setTracking(False)
        self.clahe_check = QCheckBox("CLAHE")
        self.clahe_check.setChecked(adjust.clahe_enabled)
        self.clahe_row = SliderRow("CLAHE Clip", 10, 60, int(round(adjust.clahe_clip_limit * 10)), lambda value: f"{value / 10:.1f}")
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
        preset_row = QHBoxLayout()
        pins_btn = QPushButton("Pins")
        text_btn = QPushButton("Text")
        damage_btn = QPushButton("Damage")
        for button in (pins_btn, text_btn, damage_btn):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            preset_row.addWidget(button)
        pins_btn.clicked.connect(self.apply_pin_preset)
        text_btn.clicked.connect(self.apply_text_preset)
        damage_btn.clicked.connect(self.apply_damage_preset)
        advanced_layout.addLayout(preset_row)
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

        side_scroll = QScrollArea()
        side_scroll.setObjectName("sideScroll")
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setWidgetResizable(True)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        side_scroll.setFixedWidth(404)
        side_scroll.setWidget(panel)
        root.addWidget(side_scroll, stretch=0)
        self.setCentralWidget(central)
        self._update_next_name()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #07130f; color: #eafff3; font-size: 13px; }
            QWidget#sidePanel {
                background: #0d2018;
                border: 1px solid #1d5b3b;
                border-radius: 12px;
            }
            QScrollArea#sideScroll {
                background: transparent;
                border: none;
            }
            QScrollArea#sideScroll > QWidget > QWidget {
                background: transparent;
            }
            QScrollBar:vertical {
                background: #07130f;
                width: 10px;
                margin: 2px 0 2px 0;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #38d989;
                min-height: 36px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #77ffb4;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
                border: none;
                height: 0px;
            }
            QLabel { color: #ddffe9; }
            QLabel#titleLabel {
                color: #86ffbd;
                font-size: 22px;
                font-weight: 700;
                letter-spacing: 0px;
            }
            QLabel#subtitleLabel { color: #7fd8b2; padding-bottom: 6px; }
            QLabel#monoLabel {
                color: #b6ffda;
                font-family: Consolas, "Cascadia Mono", monospace;
                background: #07130f;
                border: 1px solid #204f37;
                border-radius: 5px;
                padding: 5px 8px;
            }
            QLabel#pathLabel {
                color: #9deec0;
                background: #07130f;
                border: 1px solid #204f37;
                border-radius: 5px;
                padding: 7px;
            }
            QLabel#statusLabel {
                color: #9deec0;
                background: #07130f;
                border: 1px solid #204f37;
                border-radius: 6px;
                padding: 8px;
            }
            QLabel#reviewHintLabel {
                color: #06110d;
                background: #58f19b;
                border: 1px solid #9dffc8;
                border-radius: 6px;
                padding: 8px;
                font-weight: 700;
            }
            QGroupBox {
                color: #86ffbd;
                border: 1px solid #23613f;
                border-radius: 8px;
                margin-top: 12px;
                padding: 10px 8px 8px 8px;
                background: #10291f;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                background: #0d2018;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background: #06110d;
                border: 1px solid #266946;
                border-radius: 5px;
                color: #eafff3;
                padding: 5px 7px;
                selection-background-color: #2ff093;
                selection-color: #00140b;
            }
            QPushButton, QToolButton {
                background: #143826;
                border: 1px solid #2b8a55;
                border-radius: 6px;
                padding: 8px 10px;
                color: #ecfff3;
                font-weight: 600;
            }
            QPushButton:hover, QToolButton:hover { background: #1c5034; border-color: #4aff9d; }
            QPushButton:pressed, QToolButton:pressed { background: #48f59b; color: #06110d; }
            QPushButton:disabled { color: #5a8069; background: #0c1b14; border-color: #193625; }
            QSlider::groove:horizontal { height: 5px; background: #123322; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #46e68e; border-radius: 2px; }
            QSlider::handle:horizontal {
                width: 16px;
                margin: -6px 0;
                border-radius: 8px;
                background: #b8ffdb;
                border: 1px solid #4aff9d;
            }
            QCheckBox { spacing: 8px; }
            """
        )
        self.preview.setStyleSheet(
            "background: #020806; color: #2f7d57; border: 1px solid #1d5b3b; border-radius: 12px;"
        )

    def start_camera(self) -> None:
        if self.camera_thread is not None:
            return
        self.last_frame = None
        self.last_clean_bgr = None
        self.last_annotated_bgr = None
        self.last_frame_time = 0.0
        self.capture_btn.setEnabled(True)
        self.capture_btn.setText("Capture ROI")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.review_hint_label.setText("Camera starting in chip two-stage live mode. Capture waits for the first frame.")
        self._send_light()
        self._send_input_adjust()
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
        self._update_next_name()

    def capture(self) -> None:
        self._set_status("capture requested")
        self.review_hint_label.setText("Capture requested. Checking latest frame...")
        QApplication.processEvents()
        if self.last_frame is None or self.last_clean_bgr is None:
            self._set_status("capture ignored: no frame received yet")
            self.review_hint_label.setText("No frame is available yet. Wait until the preview shows live fps/frame updates.")
            return
        if self.review_state is not None:
            self._set_review_status("capture ignored")
            return
        frame = self.last_frame
        raw_bgr = self.last_clean_bgr.copy()
        capture_adjusted = self.camera_settings.input_adjust or self.save_adjusted_check.isChecked()
        clean_bgr = (
            raw_bgr
            if self.camera_settings.input_adjust or not self.save_adjusted_check.isChecked()
            else apply_adjustments(raw_bgr, self.image_settings)
        )
        prefix = self._capture_prefix()
        self.capture_btn.setEnabled(False)
        self.capture_btn.setText("Capturing...")
        try:
            chip_box, method, score = self._initial_chip_box(frame, clean_bgr)
            record = self.storage.save_chip_roi_candidate(
                frame=frame,
                clean_bgr=clean_bgr,
                chip_box=chip_box,
                camera_settings=self.camera_settings,
                image_settings=self.image_settings,
                light_settings=self.light_settings,
                prefix=prefix,
                method=method,
                score=score,
                capture_adjusted=capture_adjusted,
            )
        except Exception as exc:  # noqa: BLE001 - surface capture failures
            self.capture_btn.setEnabled(True)
            self.capture_btn.setText("Capture ROI")
            message = self._error_summary(str(exc))
            self._set_status(f"capture failed: {message}")
            self.review_hint_label.setText(f"Capture failed: {message}")
            return
        self.review_state = RoiReviewState(
            record=record,
            clean_bgr=clean_bgr,
            box=chip_box,
            capture_adjusted=capture_adjusted,
        )
        self._set_review_controls_active(True)
        self._render_review()
        self._update_next_name()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._set_review_status(f"captured {record.image_path.name} | {method} {score:.3f}")

    def accept_roi(self) -> None:
        if self.review_state is None:
            return
        if self.review_state.box is None:
            self.mark_negative()
            return
        try:
            self.storage.update_chip_roi_label(
                self.review_state.record,
                self.review_state.clean_bgr,
                self.review_state.box,
                "accepted",
            )
        except Exception as exc:  # noqa: BLE001
            message = self._error_summary(str(exc))
            self._set_status(f"accept failed: {message}")
            self.review_hint_label.setText(f"Accept failed: {message}")
            return
        name = self.review_state.record.image_path.name
        self.review_state = None
        self._set_review_controls_active(False)
        self._update_next_name()
        self._set_status(f"accepted: {name}")
        if self.last_frame is not None:
            self._render_frame(self.last_frame)

    def mark_negative(self) -> None:
        if self.review_state is None:
            return
        try:
            self.storage.update_chip_roi_label(
                self.review_state.record,
                self.review_state.clean_bgr,
                None,
                "negative",
            )
        except Exception as exc:  # noqa: BLE001
            message = self._error_summary(str(exc))
            self._set_status(f"negative failed: {message}")
            self.review_hint_label.setText(f"Negative failed: {message}")
            return
        name = self.review_state.record.image_path.name
        self.review_state = None
        self._set_review_controls_active(False)
        self._update_next_name()
        self._set_status(f"negative: {name}")
        if self.last_frame is not None:
            self._render_frame(self.last_frame)

    def adjust_roi(self, dx: int, dy: int) -> None:
        if self.review_state is None or self.review_state.box is None:
            return
        x1, y1, x2, y2 = self.review_state.box
        self.review_state.box = clamp_box(
            (x1 + dx, y1 + dy, x2 + dx, y2 + dy),
            self.review_state.record.width,
            self.review_state.record.height,
        )
        self._render_review()
        self._set_review_status("roi moved")

    def scale_roi(self, margin: float) -> None:
        if self.review_state is None or self.review_state.box is None:
            return
        self.review_state.box = expand_box(
            self.review_state.box,
            self.review_state.record.width,
            self.review_state.record.height,
            margin,
            square=True,
        )
        self._render_review()
        self._set_review_status("roi scaled")

    def apply_pin_preset(self) -> None:
        self._set_adjustment_values(
            ImageAdjustSettings(
                brightness=-8,
                contrast=1.45,
                gamma=0.90,
                saturation=0.22,
                sharpness=1.25,
                denoise=6,
                clahe_enabled=False,
                clahe_clip_limit=2.0,
            )
        )
        self._set_status("preset: pins")

    def apply_text_preset(self) -> None:
        self._set_adjustment_values(
            ImageAdjustSettings(
                brightness=-10,
                contrast=1.55,
                gamma=0.82,
                saturation=0.25,
                sharpness=1.05,
                denoise=6,
                clahe_enabled=False,
                clahe_clip_limit=2.0,
            )
        )
        self._set_status("preset: text")

    def apply_damage_preset(self) -> None:
        self._set_adjustment_values(
            ImageAdjustSettings(
                brightness=-6,
                contrast=1.30,
                gamma=0.95,
                saturation=0.30,
                sharpness=0.85,
                denoise=6,
                clahe_enabled=False,
                clahe_clip_limit=2.0,
            )
        )
        self._set_status("preset: damage")

    def reset_adjustments(self) -> None:
        self._set_adjustment_values(ImageAdjustSettings())
        self._set_status("preset: default")

    def _set_adjustment_values(self, settings: ImageAdjustSettings) -> None:
        self.brightness_row.set_value(settings.brightness)
        self.contrast_row.set_value(int(round(settings.contrast * 100)))
        self.gamma_row.set_value(int(round(settings.gamma * 100)))
        self.saturation_row.set_value(int(round(settings.saturation * 100)))
        self.sharpness_row.set_value(int(round(settings.sharpness * 100)))
        self.denoise_row.set_value(settings.denoise)
        self.clahe_check.setChecked(settings.clahe_enabled)
        self.clahe_row.set_value(int(round(settings.clahe_clip_limit * 10)))
        self._image_settings_changed()

    def _mode_changed(self, mode_id: int) -> None:
        live = mode_id == 1
        self.live_overlay_enabled = live
        self.draw_detections_check.setChecked(live)
        if live:
            self.review_hint_label.setText("Live Detect active. Tune Advanced sliders, then Capture ROI to freeze this adjusted view.")
        else:
            self.review_hint_label.setText("Capture / Label active. Tune the view, capture, then adjust the chip ROI.")
        if self.review_state is None and self.last_frame is not None:
            self._render_frame(self.last_frame)

    def _live_overlay_changed(self, checked: bool) -> None:
        self.live_overlay_enabled = checked
        if self.review_state is None and self.last_frame is not None:
            self._render_frame(self.last_frame)

    def _seg_model_toggled(self, checked: bool) -> None:
        self.camera_settings.defect_model_kind = "seg" if checked else "detect"
        self.camera_settings.remote_defect_model = CHIP_DEFECT_SEG_REMOTE_MODEL if checked else CHIP_REMOTE_MODEL
        if self.camera_settings.profile.endswith("maixcam"):
            self.camera_settings.profile = "chip-two-stage-seg-maixcam" if checked else "chip-two-stage-maixcam"
        else:
            self.camera_settings.profile = "chip-two-stage-seg-imx678" if checked else "chip-two-stage-imx678"
        suffix = "restart camera to apply" if self.camera_thread is not None else "ready"
        self._set_status(f"segmentation defect model {'on' if checked else 'off'} | {suffix}")

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
        self._sync_input_adjust_settings()
        self._schedule_input_adjust()
        if self.review_state is not None:
            self._render_review()
        elif self.last_frame is not None:
            self._render_frame(self.last_frame)

    def _sync_input_adjust_settings(self) -> None:
        self.camera_settings.input_brightness = self.image_settings.brightness
        self.camera_settings.input_contrast = self.image_settings.contrast
        self.camera_settings.input_gamma = self.image_settings.gamma
        self.camera_settings.input_saturation = self.image_settings.saturation
        self.camera_settings.input_sharpness = self.image_settings.sharpness

    def _input_adjust_toggled(self, checked: bool) -> None:
        self.camera_settings.input_adjust = checked
        self._sync_input_adjust_settings()
        self._schedule_input_adjust()
        if self.last_frame is not None and self.review_state is None:
            self._render_frame(self.last_frame)

    def _schedule_input_adjust(self) -> None:
        if self.camera_thread is None:
            return
        self.adjust_timer.start(120)

    def _send_input_adjust(self) -> None:
        self._sync_input_adjust_settings()
        self.adjust_executor.submit(write_input_adjust_config, self.camera_settings)

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
        self.last_frame = frame
        self.last_clean_bgr = frame.clean_bgr.copy()
        if self.review_state is not None:
            self.capture_btn.setEnabled(False)
            return
        self.capture_btn.setEnabled(True)
        self._render_frame(frame)

    def _initial_chip_box(
        self,
        frame: CameraFrame,
        image_bgr,
    ) -> tuple[tuple[int, int, int, int] | None, str, float]:
        if self.camera_settings.profile in TWO_STAGE_PROFILES:
            best_box: tuple[int, int, int, int] | None = None
            best_rank = -1.0
            best_conf = 0.0
            for detection in frame.detections:
                if detection.class_id != 0:
                    continue
                x1 = int(round(max(0.0, min(float(frame.width - 1), detection.x1))))
                y1 = int(round(max(0.0, min(float(frame.height - 1), detection.y1))))
                x2 = int(round(max(0.0, min(float(frame.width - 1), detection.x2))))
                y2 = int(round(max(0.0, min(float(frame.height - 1), detection.y2))))
                if x2 <= x1 or y2 <= y1:
                    continue
                area = float((x2 - x1) * (y2 - y1))
                rank = max(0.001, float(detection.score)) * area
                if rank > best_rank:
                    best_rank = rank
                    best_conf = float(detection.score)
                    best_box = clamp_box((x1, y1, x2, y2), frame.width, frame.height)
            if best_box is not None:
                return best_box, "board_chip_two_stage", max(0.0, best_conf)

        candidate = locate_chip_dark_edge(
            image_bgr,
            margin=0.35,
            min_side=220,
            square=True,
            max_area_ratio=0.35,
            center_bias=12.0,
        )
        if candidate is None:
            return None, "none", 0.0
        return candidate.box, candidate.method, candidate.score

    def _render_frame(self, frame: CameraFrame) -> None:
        self.last_frame = frame
        self.last_clean_bgr = frame.clean_bgr.copy()
        preview_bgr = frame.clean_bgr.copy() if self.camera_settings.input_adjust else apply_adjustments(frame.clean_bgr, self.image_settings)
        annotated_bgr = preview_bgr.copy()
        display_detections = filter_display_detections(
            frame.detections,
            frame.width,
            frame.height,
            self.camera_settings.to_namespace(),
        )
        if self.live_overlay_enabled:
            self.last_drawn_count = draw_detections(annotated_bgr, display_detections, self.class_names)
        else:
            self.last_drawn_count = 0
        self.last_annotated_bgr = annotated_bgr
        self._set_preview_image(annotated_bgr)
        self._set_status(
            f"fps {frame.fps:.1f} | focus {frame.focus:.0f} | det {len(frame.detections)}/{self.last_drawn_count} | frame {frame.frame_index}"
        )

    def _render_review(self) -> None:
        if self.review_state is None:
            return
        preview_bgr = (
            self.review_state.clean_bgr.copy()
            if self.review_state.capture_adjusted
            else apply_adjustments(self.review_state.clean_bgr, self.image_settings)
        )
        text = f"{self.review_state.record.stem} | Enter accept | Delete negative"
        self.last_annotated_bgr = draw_chip_box(preview_bgr, self.review_state.box, text)
        self._set_preview_image(self.last_annotated_bgr)

    def _set_review_controls_active(self, active: bool) -> None:
        has_box = active and self.review_state is not None and self.review_state.box is not None
        self.capture_btn.setEnabled(not active and self.last_frame is not None)
        self.capture_btn.setText("Review Pending" if active else "Capture ROI")
        self.accept_btn.setEnabled(has_box)
        self.negative_btn.setEnabled(active)
        for button in self.roi_tune_buttons:
            button.setEnabled(has_box)
        if active:
            if has_box:
                self.review_hint_label.setText("ROI review active on the captured adjusted frame: W/A/S/D move, +/- scale, Enter accept, Delete negative.")
            else:
                self.review_hint_label.setText("ROI review active: no box was found. Use Negative for this frame.")
        else:
            if self.live_overlay_enabled:
                self.review_hint_label.setText("Live Detect active. Tune Advanced sliders, then Capture ROI to freeze this adjusted view.")
            else:
                self.review_hint_label.setText("Capture a frame to enter ROI review.")

    def _set_review_status(self, prefix: str) -> None:
        if self.review_state is None:
            return
        if self.review_state.box is None:
            self._set_status(f"{prefix} | review active | no ROI box | Delete negative")
            return
        x1, y1, x2, y2 = self.review_state.box
        self._set_status(
            f"{prefix} | review active | box {x1},{y1},{x2},{y2} | Enter accept / Delete negative"
        )

    def _capture_prefix(self) -> str:
        raw = self.prefix_edit.text().strip() or "chip"
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)
        return safe.strip("_") or "chip"

    def _update_next_name(self) -> None:
        if not hasattr(self, "next_name_label"):
            return
        prefix = self._capture_prefix()
        self.next_name_label.setText(f"{self.storage.next_stem(prefix)}.jpg")

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

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            super().keyPressEvent(event)
            return
        key = event.key()
        step = self.step_spin.value() if hasattr(self, "step_spin") else 4
        scale_step = float(self.scale_spin.value()) if hasattr(self, "scale_spin") else 0.005
        if key == Qt.Key.Key_A:
            self.adjust_roi(-step, 0)
        elif key == Qt.Key.Key_D:
            self.adjust_roi(step, 0)
        elif key == Qt.Key.Key_W:
            self.adjust_roi(0, -step)
        elif key == Qt.Key.Key_S:
            self.adjust_roi(0, step)
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.scale_roi(scale_step)
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.scale_roi(-scale_step)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept_roi()
        elif key == Qt.Key.Key_Delete:
            self.mark_negative()
        else:
            super().keyPressEvent(event)

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

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self.stop_camera()
        try:
            self.light_executor.submit(self.light_controller.off).result(timeout=2)
        except Exception:
            pass
        self.light_executor.shutdown(wait=True, cancel_futures=True)
        self.adjust_executor.shutdown(wait=True, cancel_futures=True)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.shutdown()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec_()

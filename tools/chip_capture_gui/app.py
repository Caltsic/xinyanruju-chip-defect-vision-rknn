from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import cv2
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QCloseEvent, QFont, QFontDatabase, QImage, QKeyEvent, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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
    QStyle,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tools.chip_roi_utils import clamp_box, locate_chip_dark_edge
from tools.adb_imx415_rknn_live_view import (
    CHIP_REMOTE_MODEL,
    TWO_STAGE_PROFILES,
    draw_detections,
    filter_display_detections,
    profile_defaults,
)

from .camera import RknnCamera, create_camera, format_stream_error, write_input_adjust_config
from .image_adjust import apply_adjustments
from .models import CameraFrame
from .obb_refine import refine_chip_obbs_in_frame
from .seg_sample import SegSampleWriter
from .settings import (
    CameraSettings,
    ImageAdjustSettings,
    LightSettings,
    OBB_CALIBRATION_PROFILE,
    PROJECT_ROOT,
    apply_obb_calibration_preset,
    default_defect_model_for_profile,
)
from .voice_assistant import VoiceAssistantController, VoiceAssistantSettings
from .ws2812 import create_ws2812_controller


NO_FRAME_TIMEOUT_MS = 8000
PROFILE_CHOICES = (
    ("chip-two-stage-obb-seg-imx678", "IMX678 OBB seg"),
    ("chip-two-stage-seg-imx678", "IMX678 seg"),
    ("chip-two-stage-imx678", "IMX678 detect"),
    ("chip-two-stage-seg-maixcam", "MaixCAM seg"),
    ("chip-two-stage-maixcam", "MaixCAM detect"),
)
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
NEKO_IMAGE_CANDIDATES = (
    ASSETS_DIR / "neko_assistant.png",
    ASSETS_DIR / "neko_assistant.jpg",
    ASSETS_DIR / "neko_assistant.svg",
)
FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"),
)
LIGHT_PRESET_PATH = PROJECT_ROOT / "tmp" / "chip_capture_gui_light_presets.json"
LIGHT_CHANNELS = (
    ("close", "Close Ring", "brightness", "close_rgb"),
    ("high", "High Ring", "high_brightness", "high_rgb"),
    ("low", "Low Ring", "low_brightness", "low_rgb"),
    ("backlight", "Backlight", "backlight_brightness", "backlight_rgb"),
)
LIGHT_CHANNEL_BY_KEY = {channel[0]: channel for channel in LIGHT_CHANNELS}


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _normalize_rgb(value: object) -> tuple[int, int, int]:
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    else:
        try:
            parts = list(value)  # type: ignore[arg-type]
        except TypeError:
            parts = []
    if len(parts) != 3:
        return (190, 255, 100)
    try:
        return tuple(_clamp_int(int(part), 0, 255) for part in parts)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return (190, 255, 100)


def _rgb_text(rgb: tuple[int, int, int]) -> str:
    return ",".join(str(channel) for channel in rgb)


def _install_font_fallback() -> None:
    app = QApplication.instance()
    if app is None:
        return
    for font_path in FONT_CANDIDATES:
        if not font_path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
            return


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


class CompactSliderRow(QWidget):
    value_changed = pyqtSignal(int)

    def __init__(
        self,
        name: str,
        minimum: int,
        maximum: int,
        value: int,
        suffix: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.suffix = suffix
        self.label = QLabel(name)
        self.value_label = QLabel("")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._update_value)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.label.setFixedWidth(78)
        self.value_label.setFixedWidth(44)
        layout.addWidget(self.label)
        layout.addWidget(self.slider, stretch=1)
        layout.addWidget(self.value_label)
        self._update_value()

    def value(self) -> int:
        return int(self.slider.value())

    def set_value(self, value: int) -> None:
        self.slider.setValue(value)

    def _update_value(self) -> None:
        value = self.value()
        self.value_label.setText(f"{value}{self.suffix}")
        self.value_changed.emit(value)


class MainWindow(QMainWindow):
    light_error = pyqtSignal(str)
    voice_status_changed = pyqtSignal(str)

    def __init__(
        self,
        camera_settings: CameraSettings | None = None,
        board_ui: bool = False,
        seg_output_dir: Path | None = None,
        seg_prefix: str = "seg",
        light_settings: LightSettings | None = None,
        voice_settings: VoiceAssistantSettings | None = None,
    ) -> None:
        super().__init__()
        _install_font_fallback()
        self.board_ui = board_ui
        self.camera_settings = camera_settings or CameraSettings()
        self.image_settings = ImageAdjustSettings()
        self.light_settings = light_settings or LightSettings()
        voice_enabled = self.camera_settings.backend == "local" or board_ui
        if voice_settings is None:
            voice_settings = VoiceAssistantSettings(enabled=voice_enabled)
        self.voice_controller = VoiceAssistantController(
            voice_settings,
            status_callback=self.voice_status_changed.emit,
        )
        self.seg_writer = SegSampleWriter(output_dir=seg_output_dir, prefix=seg_prefix)
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
        self.class_names = list(profile_defaults(self.camera_settings.profile)[3])
        self.live_overlay_enabled = True
        self.show_raw_frame = False
        self.tools_collapsed = bool(board_ui)
        self._shutting_down = False
        self._last_voice_overlay_text = ""
        self._light_editor_updating = False
        self.light_presets = self._load_light_presets()

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
        self.voice_status_changed.connect(self._on_voice_status)
        self.voice_overlay_timer = QTimer(self)
        self.voice_overlay_timer.timeout.connect(self._update_voice_overlay)
        self.voice_overlay_timer.start(250)

        self._build_ui()
        self._apply_style()
        self._set_status("ready")

    def _build_ui(self) -> None:
        compact = self.board_ui
        self.setWindowTitle("ChipCheck Qt" if compact else "ChipCheck Seg Studio")
        self.resize(800 if compact else 1460, 600 if compact else 860)
        margin = 8 if compact else 18
        spacing = 10 if compact else 18
        panel_width = 280 if compact else 468
        scroll_width = 304 if compact else 504
        preview_min = (1, 1) if compact else (800, 560)
        neko_height = 78 if compact else 150
        neko_size = 92 if compact else 174
        primary_height = 44 if compact else 56

        central = QWidget()
        central.setObjectName("rootSurface")
        if compact:
            root = QGridLayout(central)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)
        else:
            root = QHBoxLayout(central)
            root.setContentsMargins(margin, margin, margin, margin)
            root.setSpacing(spacing)

        self.preview = QLabel("No Signal")
        self.preview.setObjectName("previewSurface")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(*preview_min)
        self.preview.setFrameShape(QFrame.Shape.NoFrame)
        self.voice_overlay = QTextEdit(self.preview)
        self.voice_overlay.setObjectName("voiceReplyOverlay")
        self.voice_overlay.setReadOnly(True)
        self.voice_overlay.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.voice_overlay.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.voice_overlay.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.voice_overlay.hide()
        self._build_light_overlay()
        if compact:
            root.addWidget(self.preview, 0, 0)
        else:
            root.addWidget(self.preview, stretch=1)

        self.side_panel = QWidget()
        self.side_panel.setObjectName("sidePanel")
        self.side_panel.setFixedWidth(panel_width)
        panel_layout = QVBoxLayout(self.side_panel)
        panel_layout.setContentsMargins(margin, margin, margin, margin)
        panel_layout.setSpacing(9 if compact else 14)

        title = QLabel("CHIPCHECK QT" if compact else "CHIPCHECK SEG")
        title.setObjectName("titleLabel")
        subtitle = QLabel("local segmentation capture" if compact else "mask-first inspection / CVAT sample capture")
        subtitle.setObjectName("subtitleLabel")
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)

        self.neko_label = QLabel()
        self.neko_label.setObjectName("nekoPanelArt")
        self.neko_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.neko_label.setMinimumHeight(neko_height)
        neko_pixmap = self._load_neko_pixmap()
        if not neko_pixmap.isNull():
            self.neko_label.setPixmap(
                neko_pixmap.scaled(
                    neko_size,
                    neko_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        panel_layout.addWidget(self.neko_label)

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
        if self.board_ui:
            quit_btn = QPushButton("Quit")
            quit_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton))
            quit_btn.clicked.connect(self.close)
            top_row.addWidget(quit_btn)
        panel_layout.addLayout(top_row)

        voice_box = QGroupBox("Voice")
        voice_layout = QGridLayout(voice_box)
        self.voice_start_btn = QPushButton("Start Mic")
        self.voice_start_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.voice_start_btn.clicked.connect(self.start_voice_recording)
        self.voice_stop_btn = QPushButton("Stop Mic")
        self.voice_stop_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.voice_stop_btn.clicked.connect(self.stop_voice_recording)
        self.voice_replay_btn = QPushButton("Replay")
        self.voice_replay_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self.voice_replay_btn.clicked.connect(self.replay_voice_reply)
        self.voice_status_label = QLabel(self.voice_controller.snapshot_status())
        self.voice_status_label.setObjectName("voiceStatusLabel")
        self.voice_status_label.setWordWrap(True)
        voice_layout.addWidget(self.voice_start_btn, 0, 0)
        voice_layout.addWidget(self.voice_stop_btn, 0, 1)
        voice_layout.addWidget(self.voice_replay_btn, 1, 0, 1, 2)
        voice_layout.addWidget(self.voice_status_label, 2, 0, 1, 2)
        panel_layout.addWidget(voice_box)
        self._sync_voice_buttons()

        mode_box = QGroupBox("Inspection")
        mode_layout = QGridLayout(mode_box)
        mode_layout.setColumnStretch(0, 1)
        self.draw_masks_check = QCheckBox("Mask / contour overlay")
        self.draw_masks_check.setChecked(self.camera_settings.defect_model_kind == "seg")
        self.draw_masks_check.toggled.connect(self._live_overlay_changed)
        self.raw_view_check = QCheckBox("Show original frame")
        self.raw_view_check.setChecked(False)
        self.raw_view_check.toggled.connect(self._raw_view_changed)
        self.seg_model_check = QCheckBox("Use segmentation defect model")
        self.seg_model_check.setChecked(self.camera_settings.defect_model_kind == "seg")
        self.seg_model_check.toggled.connect(self._seg_model_toggled)
        self.profile_combo = QComboBox()
        for profile, label in PROFILE_CHOICES:
            self.profile_combo.addItem(label, profile)
        self._select_profile_combo(self.camera_settings.profile)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.input_adjust_check = QCheckBox("Sync view to NPU input")
        self.input_adjust_check.setChecked(self.camera_settings.input_adjust)
        self.input_adjust_check.toggled.connect(self._input_adjust_toggled)
        mode_layout.addWidget(self.seg_model_check, 0, 0)
        mode_layout.addWidget(self.profile_combo, 1, 0)
        mode_layout.addWidget(self.draw_masks_check, 2, 0)
        mode_layout.addWidget(self.raw_view_check, 3, 0)
        mode_layout.addWidget(self.input_adjust_check, 4, 0)
        panel_layout.addWidget(mode_box)

        folder_box = QGroupBox("Segmentation Output")
        folder_layout = QVBoxLayout(folder_box)
        self.seg_folder_label = QLabel(str(self.seg_writer.output_dir))
        self.seg_folder_label.setObjectName("pathLabel")
        self.seg_folder_label.setWordWrap(True)
        self.seg_folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        folder_layout.addWidget(self.seg_folder_label)
        panel_layout.addWidget(folder_box)

        self.seg_save_btn = QPushButton("Save Seg Sample")
        self.seg_save_btn.setObjectName("primaryButton")
        self.seg_save_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.seg_save_btn.setMinimumHeight(primary_height)
        self.seg_save_btn.setEnabled(False)
        self.seg_save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.seg_save_btn.clicked.connect(self.save_seg_sample)
        panel_layout.addWidget(self.seg_save_btn)

        self.photo_save_btn = QPushButton("Save Photo Pair")
        self.photo_save_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.photo_save_btn.setMinimumHeight(38 if compact else 44)
        self.photo_save_btn.setEnabled(False)
        self.photo_save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.photo_save_btn.clicked.connect(self.save_photo_pair)
        panel_layout.addWidget(self.photo_save_btn)

        self.seg_hint_label = QLabel("Start the camera, keep the mask overlay clean, then save one CVAT segmentation sample per chip state.")
        self.seg_hint_label.setObjectName("segHintLabel")
        self.seg_hint_label.setWordWrap(True)
        panel_layout.addWidget(self.seg_hint_label)

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

        self.scroll_area = QScrollArea(central if compact else None)
        self.scroll_area.setObjectName("sideScroll")
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setFixedWidth(scroll_width)
        self.scroll_area.setWidget(self.side_panel)
        if compact:
            self.scroll_area.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.scroll_area.viewport().setAutoFillBackground(False)
            self.scroll_area.setVisible(False)
            self.tools_toggle_btn = QToolButton(central)
            self.tools_toggle_btn.setObjectName("toolToggle")
            self.tools_toggle_btn.setArrowType(Qt.ArrowType.LeftArrow)
            self.tools_toggle_btn.setFixedSize(48, 48)
            self.tools_toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.tools_toggle_btn.clicked.connect(self._toggle_tools_panel)
            self.tools_toggle_btn.raise_()
        else:
            root.addWidget(self.scroll_area, stretch=0)
        self.setCentralWidget(central)
        if compact:
            QTimer.singleShot(0, self._position_board_overlay)

    def _build_light_overlay(self) -> None:
        self.light_toggle_btn = QToolButton(self.preview)
        self.light_toggle_btn.setObjectName("lightDockToggle")
        self.light_toggle_btn.setText("LIGHT")
        self.light_toggle_btn.setCheckable(True)
        self.light_toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.light_toggle_btn.clicked.connect(self._toggle_light_panel)
        self.light_toggle_btn.setFixedSize(118, 38)

        self.light_panel = QWidget(self.preview)
        self.light_panel.setObjectName("lightDockPanel")
        self.light_panel.setVisible(False)
        panel_layout = QVBoxLayout(self.light_panel)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(8)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        self.light_preset_combo = QComboBox()
        self.light_preset_combo.setObjectName("lightPresetCombo")
        self.light_preset_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.light_apply_preset_btn = QPushButton("Apply")
        self.light_default_btn = QPushButton("Default")
        self.light_preset_name = QLineEdit()
        self.light_preset_name.setPlaceholderText("Preset name")
        self.light_save_preset_btn = QPushButton("Save")
        for button in (self.light_apply_preset_btn, self.light_default_btn, self.light_save_preset_btn):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        preset_row.addWidget(self.light_preset_combo, stretch=2)
        preset_row.addWidget(self.light_apply_preset_btn)
        preset_row.addWidget(self.light_default_btn)
        preset_row.addWidget(self.light_preset_name, stretch=2)
        preset_row.addWidget(self.light_save_preset_btn)
        panel_layout.addLayout(preset_row)

        channel_row = QHBoxLayout()
        channel_row.setSpacing(10)
        self.light_channel_combo = QComboBox()
        self.light_channel_combo.setObjectName("lightChannelCombo")
        self.light_channel_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for key, label, _brightness_attr, _rgb_attr in LIGHT_CHANNELS:
            self.light_channel_combo.addItem(label, key)
        self.light_swatch = QLabel()
        self.light_swatch.setObjectName("lightSwatch")
        self.light_swatch.setFixedWidth(116)
        self.light_swatch.setAlignment(Qt.AlignmentFlag.AlignCenter)
        channel_row.addWidget(self.light_channel_combo, stretch=1)
        channel_row.addWidget(self.light_swatch)
        panel_layout.addLayout(channel_row)

        max_percent = int(round(self.light_settings.max_brightness * 100))
        self.light_brightness_slider = CompactSliderRow(
            "Brightness",
            0,
            max_percent,
            int(round(self.light_settings.brightness * 100)),
            "%",
        )
        self.light_r_slider = CompactSliderRow("Red", 0, 255, self.light_settings.close_rgb[0])
        self.light_g_slider = CompactSliderRow("Green", 0, 255, self.light_settings.close_rgb[1])
        self.light_b_slider = CompactSliderRow("Blue", 0, 255, self.light_settings.close_rgb[2])
        for row in (
            self.light_brightness_slider,
            self.light_r_slider,
            self.light_g_slider,
            self.light_b_slider,
        ):
            row.value_changed.connect(self._light_editor_changed)
            panel_layout.addWidget(row)

        self.light_apply_preset_btn.clicked.connect(self._apply_selected_light_preset)
        self.light_default_btn.clicked.connect(lambda: self._apply_light_state(self._factory_light_state(), "light preset: default"))
        self.light_save_preset_btn.clicked.connect(self._save_current_light_preset)
        self.light_channel_combo.currentIndexChanged.connect(self._load_light_channel_editor)
        self._refresh_light_preset_combo()
        self._load_light_channel_editor()

    def _factory_light_state(self) -> dict[str, object]:
        defaults = LightSettings()
        return {
            "brightness": defaults.brightness,
            "high_brightness": defaults.high_brightness,
            "low_brightness": defaults.low_brightness,
            "backlight_brightness": defaults.backlight_brightness,
            "close_rgb": list(defaults.close_rgb),
            "high_rgb": list(defaults.high_rgb),
            "low_rgb": list(defaults.low_rgb),
            "backlight_rgb": list(defaults.backlight_rgb),
        }

    def _light_state_from_settings(self) -> dict[str, object]:
        return {
            "brightness": self.light_settings.brightness,
            "high_brightness": self.light_settings.high_brightness,
            "low_brightness": self.light_settings.low_brightness,
            "backlight_brightness": self.light_settings.backlight_brightness,
            "close_rgb": list(self.light_settings.close_rgb),
            "high_rgb": list(self.light_settings.high_rgb),
            "low_rgb": list(self.light_settings.low_rgb),
            "backlight_rgb": list(self.light_settings.backlight_rgb),
        }

    def _normalized_light_state(self, state: object) -> dict[str, object]:
        if not isinstance(state, dict):
            state = {}
        defaults = self._factory_light_state()
        normalized: dict[str, object] = {}
        for _key, _label, brightness_attr, rgb_attr in LIGHT_CHANNELS:
            try:
                brightness = float(state.get(brightness_attr, defaults[brightness_attr]))  # type: ignore[union-attr]
            except (TypeError, ValueError):
                brightness = float(defaults[brightness_attr])
            normalized[brightness_attr] = max(0.0, min(self.light_settings.max_brightness, brightness))
            rgb_value = state.get(rgb_attr, state.get("rgb", defaults[rgb_attr]))  # type: ignore[union-attr]
            normalized[rgb_attr] = list(_normalize_rgb(rgb_value))
        return normalized

    def _load_light_presets(self) -> list[dict[str, object]]:
        try:
            payload = json.loads(LIGHT_PRESET_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        records = payload.get("presets", []) if isinstance(payload, dict) else []
        if not isinstance(records, list):
            return []
        presets: list[dict[str, object]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            name = str(record.get("name", "")).strip()
            if not name:
                continue
            presets.append({"name": name[:48], "state": self._normalized_light_state(record.get("state", {}))})
        return presets

    def _save_light_presets(self) -> None:
        LIGHT_PRESET_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"presets": self.light_presets}
        LIGHT_PRESET_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _refresh_light_preset_combo(self, selected_name: str | None = None) -> None:
        if not hasattr(self, "light_preset_combo"):
            return
        blocked = self.light_preset_combo.blockSignals(True)
        self.light_preset_combo.clear()
        self.light_preset_combo.addItem("Default RGB 190,255,100", self._factory_light_state())
        for preset in self.light_presets:
            self.light_preset_combo.addItem(str(preset["name"]), preset["state"])
        if selected_name:
            index = self.light_preset_combo.findText(selected_name)
            if index >= 0:
                self.light_preset_combo.setCurrentIndex(index)
        self.light_preset_combo.blockSignals(blocked)

    def _apply_selected_light_preset(self) -> None:
        state = self.light_preset_combo.currentData()
        label = self.light_preset_combo.currentText() or "preset"
        self._apply_light_state(state, f"light preset: {label}")

    def _apply_light_state(self, state: object, status: str) -> None:
        normalized = self._normalized_light_state(state)
        for _key, _label, brightness_attr, rgb_attr in LIGHT_CHANNELS:
            setattr(self.light_settings, brightness_attr, float(normalized[brightness_attr]))
            setattr(self.light_settings, rgb_attr, tuple(normalized[rgb_attr]))  # type: ignore[arg-type]
        self.light_settings.rgb = self.light_settings.close_rgb
        self._load_light_channel_editor()
        self._update_light_swatch()
        self._schedule_light()
        self._set_status(status)

    def _save_current_light_preset(self) -> None:
        name = self.light_preset_name.text().strip()
        if not name:
            name = time.strftime("Light %H%M%S")
        state = self._light_state_from_settings()
        replacement = {"name": name[:48], "state": state}
        for index, preset in enumerate(self.light_presets):
            if str(preset.get("name", "")).casefold() == name.casefold():
                self.light_presets[index] = replacement
                break
        else:
            self.light_presets.append(replacement)
        try:
            self._save_light_presets()
        except OSError as exc:
            self._set_status(f"light preset save failed: {self._error_summary(str(exc))}")
            return
        self._refresh_light_preset_combo(replacement["name"])
        self.light_preset_name.clear()
        self._set_status(f"light preset saved: {replacement['name']}")

    def _current_light_channel_key(self) -> str:
        if not hasattr(self, "light_channel_combo"):
            return "close"
        key = self.light_channel_combo.currentData()
        return str(key) if key in LIGHT_CHANNEL_BY_KEY else "close"

    def _current_light_fields(self) -> tuple[str, str]:
        _key, _label, brightness_attr, rgb_attr = LIGHT_CHANNEL_BY_KEY[self._current_light_channel_key()]
        return brightness_attr, rgb_attr

    def _load_light_channel_editor(self, _index: int | None = None) -> None:
        if not hasattr(self, "light_brightness_slider"):
            return
        brightness_attr, rgb_attr = self._current_light_fields()
        rgb = _normalize_rgb(getattr(self.light_settings, rgb_attr))
        brightness = int(round(float(getattr(self.light_settings, brightness_attr)) * 100))
        self._light_editor_updating = True
        try:
            self.light_brightness_slider.set_value(brightness)
            self.light_r_slider.set_value(rgb[0])
            self.light_g_slider.set_value(rgb[1])
            self.light_b_slider.set_value(rgb[2])
        finally:
            self._light_editor_updating = False
        self._update_light_swatch()

    def _light_editor_changed(self, _value: int = 0) -> None:
        if self._light_editor_updating:
            return
        brightness_attr, rgb_attr = self._current_light_fields()
        rgb = (
            self.light_r_slider.value(),
            self.light_g_slider.value(),
            self.light_b_slider.value(),
        )
        setattr(self.light_settings, brightness_attr, self.light_brightness_slider.value() / 100)
        setattr(self.light_settings, rgb_attr, rgb)
        if rgb_attr == "close_rgb":
            self.light_settings.rgb = rgb
        self._update_light_swatch()
        self._schedule_light()

    def _update_light_swatch(self) -> None:
        if not hasattr(self, "light_swatch"):
            return
        rgb = (
            self.light_r_slider.value(),
            self.light_g_slider.value(),
            self.light_b_slider.value(),
        )
        text_color = "#07100f" if sum(rgb) > 360 else "#edf8ef"
        self.light_swatch.setText(_rgb_text(rgb))
        self.light_swatch.setStyleSheet(
            "QLabel#lightSwatch { "
            f"background: rgb({rgb[0]}, {rgb[1]}, {rgb[2]}); "
            f"color: {text_color}; "
            "border: 1px solid rgba(237, 248, 239, 190); "
            "border-radius: 6px; "
            "padding: 7px 8px; "
            "font-weight: 800; "
            "}"
        )

    def _toggle_light_panel(self, checked: bool) -> None:
        self.light_panel.setVisible(checked)
        self._position_light_overlay()

    def _load_neko_pixmap(self) -> QPixmap:
        for path in NEKO_IMAGE_CANDIDATES:
            if not path.exists():
                continue
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return pixmap
        return QPixmap()

    def _apply_style(self) -> None:
        style = """
            QMainWindow, QWidget { background: #0d1214; color: #edf8ef; font-size: 15px; }
            QWidget#rootSurface {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #10181b, stop:0.52 #0d1412, stop:1 #181516);
            }
            QWidget#sidePanel {
                background: rgba(18, 29, 29, 232);
                border: 1px solid #2d6a61;
                border-radius: 8px;
            }
            QScrollArea#sideScroll {
                background: transparent;
                border: none;
            }
            QScrollArea#sideScroll > QWidget > QWidget {
                background: transparent;
            }
            QScrollBar:vertical {
                background: #11191a;
                width: 12px;
                margin: 2px 0 2px 0;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #4fb99b;
                min-height: 36px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background: #d6f26a;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
                border: none;
                height: 0px;
            }
            QLabel { color: #edf8ef; }
            QLabel#titleLabel {
                color: #d6f26a;
                font-size: 26px;
                font-weight: 700;
                letter-spacing: 0px;
            }
            QLabel#subtitleLabel { color: #92c9b5; padding-bottom: 6px; }
            QLabel#nekoPanelArt {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #121d1d, stop:0.55 #17342f, stop:1 #203c35);
                border: 1px solid #2d6a61;
                border-radius: 8px;
                padding: 0 18px;
            }
            QLabel#monoLabel {
                color: #d6f26a;
                font-family: Consolas, "Cascadia Mono", monospace;
                background: #0d1214;
                border: 1px solid #2d6a61;
                border-radius: 5px;
                padding: 5px 8px;
            }
            QLabel#pathLabel {
                color: #b8d9cc;
                background: #0d1214;
                border: 1px solid #2d6a61;
                border-radius: 5px;
                padding: 9px;
            }
            QLabel#statusLabel {
                color: #b8d9cc;
                background: #0d1214;
                border: 1px solid #2d6a61;
                border-radius: 6px;
                padding: 10px;
            }
            QTextEdit#voiceReplyOverlay {
                color: #40ff60;
                background: rgba(0, 0, 0, 176);
                border: 1px solid rgba(64, 255, 96, 210);
                border-radius: 6px;
                padding: 8px;
                font-size: 20px;
            }
            QLabel#segHintLabel {
                color: #211918;
                background: #f4c46b;
                border: 1px solid #ffe09a;
                border-radius: 7px;
                padding: 10px;
                font-weight: 700;
            }
            QGroupBox {
                color: #d6f26a;
                border: 1px solid #2d6a61;
                border-radius: 8px;
                margin-top: 12px;
                padding: 12px 10px 10px 10px;
                background: #121d1d;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                background: #121d1d;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background: #0d1214;
                border: 1px solid #2d6a61;
                border-radius: 5px;
                color: #edf8ef;
                padding: 7px 9px;
                selection-background-color: #4fb99b;
                selection-color: #07100f;
            }
            QComboBox {
                background: #0d1214;
                border: 1px solid #2d6a61;
                border-radius: 5px;
                color: #edf8ef;
                padding: 7px 9px;
                selection-background-color: #4fb99b;
                selection-color: #07100f;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background: #0d1214;
                border: 1px solid #2d6a61;
                color: #edf8ef;
                selection-background-color: #4fb99b;
                selection-color: #07100f;
            }
            QPushButton, QToolButton {
                background: #17342f;
                border: 1px solid #3d7f72;
                border-radius: 6px;
                padding: 11px 14px;
                color: #edf8ef;
                font-weight: 600;
            }
            QPushButton#primaryButton {
                background: #d6f26a;
                border: 1px solid #f4c46b;
                color: #111915;
                font-size: 17px;
                font-weight: 800;
            }
            QPushButton:hover, QToolButton:hover { background: #1f4a42; border-color: #d6f26a; }
            QPushButton#primaryButton:hover { background: #ecff8f; border-color: #ffe09a; }
            QPushButton:pressed, QToolButton:pressed { background: #4fb99b; color: #07100f; }
            QPushButton:disabled { color: #667a73; background: #10191a; border-color: #1d3330; }
            QSlider::groove:horizontal { height: 6px; background: #20302f; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #4fb99b; border-radius: 3px; }
            QSlider::handle:horizontal {
                width: 18px;
                margin: -7px 0;
                border-radius: 9px;
                background: #f4c46b;
                border: 1px solid #ffe09a;
            }
            QCheckBox { spacing: 10px; }
            QToolButton#lightDockToggle {
                background: rgba(8, 13, 14, 196);
                border: 1px solid rgba(214, 242, 106, 205);
                border-radius: 19px;
                color: #d6f26a;
                padding: 0px;
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 0px;
            }
            QToolButton#lightDockToggle:checked,
            QToolButton#lightDockToggle:hover {
                background: rgba(31, 74, 66, 224);
                border-color: #ecff8f;
                color: #edf8ef;
            }
            QWidget#lightDockPanel {
                background: rgba(8, 13, 14, 224);
                border: 1px solid rgba(214, 242, 106, 185);
                border-radius: 8px;
            }
            QWidget#lightDockPanel QLabel {
                background: transparent;
                color: #edf8ef;
            }
            QWidget#lightDockPanel QLineEdit,
            QWidget#lightDockPanel QComboBox {
                background: rgba(13, 18, 20, 222);
                border-color: rgba(79, 185, 155, 190);
            }
            QWidget#lightDockPanel QPushButton {
                padding: 8px 11px;
                background: rgba(23, 52, 47, 226);
            }
            """
        if self.board_ui:
            style = (
                style.replace("font-size: 15px;", "font-size: 13px;")
                .replace("font-size: 26px;", "font-size: 20px;")
                .replace("font-size: 17px;", "font-size: 14px;")
                .replace("padding: 11px 14px;", "padding: 8px 10px;")
                .replace("padding: 12px 10px 10px 10px;", "padding: 9px 8px 8px 8px;")
                .replace("margin-top: 12px;", "margin-top: 9px;")
                .replace("padding: 10px;", "padding: 8px;")
                .replace("padding: 9px;", "padding: 7px;")
                .replace("padding: 0 18px;", "padding: 0 8px;")
            )
            style += """
            QWidget#rootSurface { background: #05090a; }
            QWidget#sidePanel {
                background: rgba(18, 29, 29, 198);
                border: 1px solid rgba(79, 185, 155, 190);
                border-radius: 8px;
            }
            QScrollArea#sideScroll {
                background: transparent;
                border: none;
            }
            QScrollArea#sideScroll > QWidget,
            QScrollArea#sideScroll > QWidget > QWidget {
                background: transparent;
            }
            QToolButton#toolToggle {
                background: rgba(13, 18, 20, 218);
                border: 1px solid rgba(214, 242, 106, 220);
                border-radius: 6px;
                padding: 0px;
            }
            QToolButton#toolToggle:hover {
                background: rgba(31, 74, 66, 230);
                border-color: #ecff8f;
            }
            QGroupBox {
                background: rgba(18, 29, 29, 168);
                border: 1px solid rgba(79, 185, 155, 160);
            }
            QGroupBox::title { background: transparent; }
            QLabel#nekoPanelArt,
            QLabel#pathLabel,
            QLabel#statusLabel {
                background: rgba(8, 13, 14, 176);
                border-color: rgba(79, 185, 155, 150);
            }
            QLabel#segHintLabel {
                background: rgba(244, 196, 107, 210);
            }
            """
        self.setStyleSheet(style)
        preview_style = (
            "background: #020506; color: #5b8378; border: none; border-radius: 0px;"
            if self.board_ui
            else "background: #060b0d; color: #5b8378; border: 1px solid #2d6a61; border-radius: 8px;"
        )
        self.preview.setStyleSheet(preview_style)

    def start_camera(self) -> None:
        if self.camera_thread is not None:
            return
        self.last_frame = None
        self.last_clean_bgr = None
        self.last_annotated_bgr = None
        self.last_frame_time = 0.0
        self.seg_save_btn.setEnabled(False)
        self.photo_save_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.seg_hint_label.setText("Camera starting in chip segmentation live mode. Seg sample saving enables after the first frame.")
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

    def save_seg_sample(self) -> None:
        self._set_status("seg sample save requested")
        if self.last_frame is None:
            self._set_status("seg sample ignored: no frame")
            self.seg_hint_label.setText("No live frame is available yet. Start the camera and wait for fps/frame updates.")
            return
        try:
            result = self.seg_writer.save(
                frame=self.last_frame,
                camera_settings=self.camera_settings,
                image_settings=self.image_settings,
                light_settings=self.light_settings,
            )
        except Exception as exc:  # noqa: BLE001 - surface save failures in GUI
            message = self._error_summary(str(exc))
            self._set_status(f"seg sample failed: {message}")
            self.seg_hint_label.setText(f"Seg sample save failed: {message}")
            return
        if result is None:
            self._set_status("seg sample ignored: no chip ROI")
            self.seg_hint_label.setText("No chip ROI was detected in the latest frame. Sample was not saved.")
            return
        self._set_status(f"seg sample saved: {result.stem}.jpg | objects {result.objects}")
        self.seg_hint_label.setText(
            f"Saved seg sample {result.stem}.jpg to {self.seg_writer.output_dir} | objects {result.objects}"
        )

    def save_photo_pair(self) -> None:
        if self.last_frame is None or self.last_clean_bgr is None:
            self._set_status("photo ignored: no frame")
            self.seg_hint_label.setText("No live frame is available yet. Start the camera and wait for fps/frame updates.")
            return
        stem = self._photo_snapshot_stem()
        original_path = self.seg_writer.output_dir / "snapshots" / "original" / f"{stem}_original.jpg"
        marked_path = self.seg_writer.output_dir / "snapshots" / "marked" / f"{stem}_marked.jpg"
        try:
            original = self.last_clean_bgr.copy()
            marked = self._build_marked_snapshot()
            self._write_snapshot_jpeg(original_path, original)
            self._write_snapshot_jpeg(marked_path, marked)
            self._append_photo_manifest(stem, original_path, marked_path)
        except Exception as exc:  # noqa: BLE001 - surface file/runtime failures in GUI
            message = self._error_summary(str(exc))
            self._set_status(f"photo save failed: {message}")
            self.seg_hint_label.setText(f"Photo save failed: {message}")
            return
        self._set_status(f"photo saved: {stem}")
        self.seg_hint_label.setText(
            f"Saved original and marked photo pair under {self.seg_writer.output_dir / 'snapshots'}"
        )

    def _photo_snapshot_stem(self) -> str:
        timestamp = time.time()
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp))
        millis = int((timestamp % 1) * 1000)
        frame_index = self.last_frame.frame_index if self.last_frame is not None else 0
        return f"photo_{stamp}_{millis:03d}_f{frame_index:06d}"

    def _write_snapshot_jpeg(self, path: Path, image) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        ok = cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise RuntimeError(f"failed to write {path}")

    def _build_marked_snapshot(self):
        if self.last_frame is None:
            raise RuntimeError("no frame")
        frame = self.last_frame
        preview_bgr = frame.clean_bgr.copy() if self.camera_settings.input_adjust else apply_adjustments(frame.clean_bgr, self.image_settings)
        marked_bgr = preview_bgr.copy()
        if self.live_overlay_enabled and self.draw_masks_check.isChecked():
            display_detections = filter_display_detections(
                frame.detections,
                frame.width,
                frame.height,
                self.camera_settings.to_namespace(),
            )
            draw_detections(
                marked_bgr,
                display_detections,
                self.class_names,
                self._draw_args("mask-contour"),
            )
        return marked_bgr

    def _append_photo_manifest(self, stem: str, original_path: Path, marked_path: Path) -> None:
        manifest_path = self.seg_writer.output_dir / "snapshots" / "manifest.csv"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = (
            "stem",
            "timestamp",
            "frame_index",
            "original",
            "marked",
            "profile",
            "detections",
            "drawn",
            "image_adjust",
            "light",
        )
        new_file = not manifest_path.exists()
        with manifest_path.open("a", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
            if new_file:
                writer.writeheader()
            writer.writerow(
                {
                    "stem": stem,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                    "frame_index": self.last_frame.frame_index if self.last_frame is not None else "",
                    "original": str(original_path.relative_to(self.seg_writer.output_dir).as_posix()),
                    "marked": str(marked_path.relative_to(self.seg_writer.output_dir).as_posix()),
                    "profile": self.camera_settings.profile,
                    "detections": len(self.last_frame.detections) if self.last_frame is not None else "",
                    "drawn": self.last_drawn_count,
                    "image_adjust": json.dumps(self.image_settings.to_json(), ensure_ascii=False, separators=(",", ":")),
                    "light": json.dumps(self.light_settings.to_json(), ensure_ascii=False, separators=(",", ":")),
                }
            )

    def start_voice_recording(self) -> None:
        self.voice_controller.start_recording()
        self._sync_voice_buttons()

    def stop_voice_recording(self) -> None:
        self.voice_controller.stop_recording()
        self._sync_voice_buttons()

    def replay_voice_reply(self) -> None:
        self.voice_controller.play_last_reply()
        self._sync_voice_buttons()

    def _on_voice_status(self, message: str) -> None:
        self.voice_status_label.setText(message)
        self._update_voice_overlay()
        self._sync_voice_buttons()

    def _sync_voice_buttons(self) -> None:
        enabled = self.voice_controller.settings.enabled
        state = self.voice_controller.state
        self.voice_start_btn.setEnabled(enabled and state == "idle")
        self.voice_stop_btn.setEnabled(enabled and state == "recording")
        self.voice_replay_btn.setEnabled(enabled and state == "idle" and self.voice_controller.reply_wav.exists())

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

    def _live_overlay_changed(self, checked: bool) -> None:
        if self.last_frame is not None:
            self._render_frame(self.last_frame)

    def _raw_view_changed(self, checked: bool) -> None:
        self.show_raw_frame = checked
        if self.last_frame is not None:
            self._render_frame(self.last_frame)
        self._set_status("original frame view" if checked else "overlay view")

    def _seg_model_toggled(self, checked: bool) -> None:
        self.camera_settings.defect_model_kind = "seg" if checked else "detect"
        self.camera_settings.remote_defect_model = default_defect_model_for_profile(
            self.camera_settings.profile,
            self.camera_settings.defect_model_kind,
        )
        self.draw_masks_check.setChecked(checked)
        if checked and self.camera_settings.profile == OBB_CALIBRATION_PROFILE:
            next_profile = OBB_CALIBRATION_PROFILE
        elif self.camera_settings.profile.endswith("maixcam"):
            next_profile = "chip-two-stage-seg-maixcam" if checked else "chip-two-stage-maixcam"
        else:
            next_profile = "chip-two-stage-seg-imx678" if checked else "chip-two-stage-imx678"
        self._apply_profile(next_profile, update_combo=True)
        suffix = "restart camera to apply" if self.camera_thread is not None else "ready"
        self._set_status(f"segmentation defect model {'on' if checked else 'off'} | {suffix}")

    def _select_profile_combo(self, profile: str) -> None:
        index = self.profile_combo.findData(profile)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)

    def _apply_profile(self, profile: str, update_combo: bool = False) -> None:
        workdir, binary, model, classes, _title = profile_defaults(profile)
        is_seg = "seg" in profile
        self.camera_settings.profile = profile
        self.camera_settings.remote_workdir = workdir
        self.camera_settings.remote_binary = binary
        self.camera_settings.remote_model = model
        self.camera_settings.defect_model_kind = "seg" if is_seg else "detect"
        self.camera_settings.remote_defect_model = default_defect_model_for_profile(
            profile,
            self.camera_settings.defect_model_kind,
        )
        apply_obb_calibration_preset(self.camera_settings)
        self.class_names = list(classes)
        if update_combo:
            blocked = self.profile_combo.blockSignals(True)
            self._select_profile_combo(profile)
            self.profile_combo.blockSignals(blocked)
        self.seg_model_check.blockSignals(True)
        self.seg_model_check.setChecked(is_seg)
        self.seg_model_check.blockSignals(False)
        self.draw_masks_check.setChecked(is_seg)

    def _profile_changed(self) -> None:
        profile = self.profile_combo.currentData()
        if not profile:
            return
        self._apply_profile(str(profile))
        suffix = "restart camera to apply" if self.camera_thread is not None else "ready"
        self._set_status(f"profile {profile} | {suffix}")

    def _toggle_advanced(self) -> None:
        visible = self.advanced_btn.isChecked()
        self.advanced_btn.setArrowType(Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)
        self.advanced_panel.setVisible(visible)
        self._position_board_overlay()

    def _toggle_tools_panel(self) -> None:
        self._set_tools_panel_collapsed(not self.tools_collapsed)

    def _set_tools_panel_collapsed(self, collapsed: bool) -> None:
        if not self.board_ui:
            return
        self.tools_collapsed = collapsed
        self.scroll_area.setVisible(not collapsed)
        self.tools_toggle_btn.setArrowType(Qt.ArrowType.LeftArrow if collapsed else Qt.ArrowType.RightArrow)
        self._position_board_overlay()

    def _position_board_overlay(self) -> None:
        if not self.board_ui or not hasattr(self, "tools_toggle_btn"):
            return
        area = self.centralWidget()
        if area is None:
            return
        width = max(1, area.width())
        height = max(1, area.height())
        panel_width = min(self.scroll_area.width(), max(220, width - 72))
        panel_margin = 8
        panel_height = max(1, height - panel_margin * 2)
        panel_x = max(panel_margin, width - panel_width - panel_margin)
        panel_y = panel_margin
        self.scroll_area.setGeometry(panel_x, panel_y, panel_width, panel_height)

        button_w = self.tools_toggle_btn.width()
        button_h = self.tools_toggle_btn.height()
        if self.tools_collapsed:
            button_x = max(0, width - button_w - panel_margin)
            button_y = max(panel_margin, (height - button_h) // 2)
        else:
            button_x = max(panel_margin, panel_x - button_w - 6)
            button_y = panel_margin + 6
        self.tools_toggle_btn.move(button_x, button_y)
        self.scroll_area.raise_()
        self.tools_toggle_btn.raise_()
        self._position_voice_overlay()
        self._position_light_overlay()

    def _position_light_overlay(self) -> None:
        if not hasattr(self, "light_toggle_btn"):
            return
        width = max(1, self.preview.width())
        height = max(1, self.preview.height())
        button_w = self.light_toggle_btn.width()
        button_h = self.light_toggle_btn.height()
        button_x = max(8, (width - button_w) // 2)
        button_y = max(8, height - button_h - 12)
        self.light_toggle_btn.move(button_x, button_y)

        panel_w = min(width - 24, 760 if not self.board_ui else 620)
        panel_w = max(320, panel_w)
        panel_h_target = 268 if not self.board_ui else 242
        panel_h = min(panel_h_target, max(188, height - button_h - 34))
        panel_x = max(12, (width - panel_w) // 2)
        panel_y = max(8, button_y - panel_h - 8)
        self.light_panel.setGeometry(panel_x, panel_y, panel_w, panel_h)
        self.light_panel.raise_()
        self.light_toggle_btn.raise_()

    def _position_voice_overlay(self) -> None:
        if not hasattr(self, "voice_overlay"):
            return
        width = max(1, self.preview.width())
        height = max(1, self.preview.height())
        overlay_w = max(260, min(width - 20, int(width * 0.70)))
        overlay_h = max(110, min(height - 20, int(height * 0.38)))
        self.voice_overlay.setGeometry(10, 10, overlay_w, overlay_h)
        self.voice_overlay.raise_()

    def _update_voice_overlay(self) -> None:
        if not hasattr(self, "voice_overlay"):
            return
        text = self.voice_controller.snapshot_reply_text().strip()
        if not text:
            self._last_voice_overlay_text = ""
            self.voice_overlay.hide()
            return
        if text != self._last_voice_overlay_text:
            self._last_voice_overlay_text = text
            self.voice_overlay.setPlainText(text)
            bar = self.voice_overlay.verticalScrollBar()
            bar.setValue(bar.maximum())
        self._position_voice_overlay()
        self.voice_overlay.show()

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
        if self.last_frame is not None:
            self._render_frame(self.last_frame)

    def _overlay_mode(self) -> str | None:
        if self.show_raw_frame or not self.live_overlay_enabled:
            return None
        return "mask-contour" if self.draw_masks_check.isChecked() else None

    def _draw_args(self, overlay_mode: str) -> SimpleNamespace:
        args = self.camera_settings.to_namespace()
        args.mask_fill = "auto"
        args.overlay_mode = overlay_mode
        args.chip_box_overlay = True
        return args

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
        if self.last_frame is not None:
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
        self.light_future = self.light_executor.submit(self.light_controller.apply)
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
        refine_chip_obbs_in_frame(frame.clean_bgr, frame.detections, frame.width, frame.height)
        self.last_frame_time = time.perf_counter()
        self.no_frame_timer.stop()
        self.last_frame = frame
        self.last_clean_bgr = frame.clean_bgr.copy()
        self.seg_save_btn.setEnabled(True)
        self.photo_save_btn.setEnabled(True)
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
        if self.show_raw_frame:
            annotated_bgr = frame.clean_bgr.copy()
            self.last_drawn_count = 0
        else:
            preview_bgr = frame.clean_bgr.copy() if self.camera_settings.input_adjust else apply_adjustments(frame.clean_bgr, self.image_settings)
            annotated_bgr = preview_bgr.copy()
            display_detections = filter_display_detections(
                frame.detections,
                frame.width,
                frame.height,
                self.camera_settings.to_namespace(),
            )
            overlay_mode = self._overlay_mode()
            if overlay_mode is not None:
                self.last_drawn_count = draw_detections(
                    annotated_bgr,
                    display_detections,
                    self.class_names,
                    self._draw_args(overlay_mode),
                )
            else:
                self.last_drawn_count = 0
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
            self._position_voice_overlay()
            self._position_light_overlay()
            return
        scaled = self.current_pixmap.scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(scaled)
        self._position_voice_overlay()
        self._position_light_overlay()

    def _on_camera_error(self, message: str) -> None:
        summary = self._error_summary(message)
        self._set_status(f"camera failed: {summary}")

    def _on_camera_stopped(self) -> None:
        self.no_frame_timer.stop()
        self.camera_thread = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.seg_save_btn.setEnabled(False)
        self.photo_save_btn.setEnabled(self.last_clean_bgr is not None)
        if self.status_label.text() in ("running", "starting"):
            self._set_status("stopped")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            super().keyPressEvent(event)
            return
        if event.key() in (Qt.Key.Key_Q, Qt.Key.Key_Escape):
            self.close()
            return
        if event.key() in (Qt.Key.Key_S, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.save_seg_sample()
            return
        if event.key() == Qt.Key.Key_P:
            self.save_photo_pair()
            return
        if event.key() == Qt.Key.Key_M:
            self.voice_controller.toggle_recording()
            self._sync_voice_buttons()
            return
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
        self._position_board_overlay()
        self._position_voice_overlay()
        self._position_light_overlay()

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self.stop_camera()
        self.voice_controller.shutdown()
        try:
            self.light_executor.submit(self.light_controller.off).result(timeout=2)
        except Exception:
            pass
        self.light_executor.shutdown(wait=True, cancel_futures=True)
        self.adjust_executor.shutdown(wait=True, cancel_futures=True)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.shutdown()
        event.accept()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PyQt ChipCheck segmentation GUI")
    parser.add_argument("--backend", choices=("adb", "local"), help="Camera/control backend")
    parser.add_argument("--adb", help="Path to adb executable for the ADB backend")
    parser.add_argument("--serial", help="ADB device serial for the ADB backend")
    parser.add_argument("--board-ui", action="store_true", help="Use compact TaishanPi HDMI layout")
    parser.add_argument("--fullscreen", action="store_true", help="Show the Qt window fullscreen")
    parser.add_argument("--screen-width", type=int, help="Initial Qt window width")
    parser.add_argument("--screen-height", type=int, help="Initial Qt window height")
    parser.add_argument("--window-x", type=int, default=0, help="Initial Qt window X position")
    parser.add_argument("--window-y", type=int, default=0, help="Initial Qt window Y position")
    parser.add_argument("--output-dir", type=Path, help="Segmentation sample output directory")
    parser.add_argument("--prefix", default="seg", help="Segmentation sample filename prefix")
    parser.add_argument("--profile", help="Runtime profile passed to the board stream binary")
    parser.add_argument("--device", help="V4L2 camera device")
    parser.add_argument("--width", type=int, help="Camera stream width")
    parser.add_argument("--height", type=int, help="Camera stream height")
    parser.add_argument("--fps", type=int, help="Camera FPS request")
    parser.add_argument("--camera-format", help="Camera format, for example mjpg")
    parser.add_argument("--conf", type=float, help="Chip model confidence")
    parser.add_argument("--chip-conf", type=float, help="Chip ROI confidence")
    parser.add_argument("--defect-conf", type=float, help="Defect confidence")
    parser.add_argument("--roi-margin", type=float, help="Chip ROI expansion ratio")
    parser.add_argument("--roi-smooth-alpha", type=float, help="Chip ROI EMA alpha; 1.0 means raw per-update ROI")
    parser.add_argument("--roi-hold", type=int, help="Frames to hold the last chip ROI after a miss")
    parser.add_argument("--chip-interval", type=int, help="Chip ROI inference interval")
    parser.add_argument("--defect-confirm", type=int, help="Board-side defect confirmation count")
    parser.add_argument("--display-max-defects", type=int, help="Max displayed defects after filtering")
    parser.add_argument("--defect-model-kind", choices=("detect", "seg"), help="Board defect postprocess kind")
    parser.add_argument("--remote-workdir", help="Board runtime work directory")
    parser.add_argument("--remote-binary", help="Board stream binary path relative to workdir or absolute")
    parser.add_argument("--remote-model", help="Chip ROI RKNN model path")
    parser.add_argument("--remote-defect-model", help="Defect RKNN model path")
    parser.add_argument("--light-brightness", type=float, default=0.50, help="WS2812 close 8 LED brightness")
    parser.add_argument("--light-high-brightness", type=float, default=0.20, help="WS2812 high-angle 12 LED brightness")
    parser.add_argument("--light-low-brightness", type=float, default=0.20, help="WS2812 low-angle 24 LED brightness")
    parser.add_argument("--light-backlight-brightness", type=float, default=0.20, help="WS2812 backlight brightness")
    parser.add_argument("--light-rgb", default="190,255,100", help="WS2812 RGB")
    parser.add_argument("--backlight-gpio", default="GPIO3_A2", help="Backlight GPIO name")
    parser.add_argument("--backlight-gpio-chip", default="gpiochip3", help="Backlight GPIO chip label")
    parser.add_argument("--backlight-gpio-line", type=int, default=2, help="Backlight GPIO line inside the bank")
    parser.add_argument("--backlight-count", type=int, default=256, help="Backlight WS2812 LED count")
    parser.add_argument("--no-backlight", action="store_true", help="Disable the independent backlight channel")
    parser.add_argument("--voice-assistant", dest="voice_assistant", action="store_true", help="Enable local voice assistant controls")
    parser.add_argument("--no-voice-assistant", dest="voice_assistant", action="store_false", help="Disable local voice assistant controls")
    parser.set_defaults(voice_assistant=None)
    parser.add_argument("--voice-command", default="", help="Command that maps input wav to result json/reply wav")
    parser.add_argument("--voice-workdir", type=Path, help="Voice assistant working directory")
    parser.add_argument("--voice-record-device", default="hw:0,0", help="ALSA capture device")
    parser.add_argument("--voice-playback-device", default="plughw:0,0", help="ALSA playback device")
    parser.add_argument("--voice-threads", type=int, default=2, help="Max CPU threads for assistant command")
    parser.add_argument("--voice-command-timeout", type=int, default=360, help="Voice assistant command timeout in seconds")
    return parser.parse_args(argv)


def _settings_from_args(args: argparse.Namespace) -> CameraSettings:
    settings = CameraSettings()
    if args.board_ui and args.backend is None:
        settings.backend = "local"
    if args.backend is not None:
        settings.backend = args.backend
        if args.profile:
            workdir, binary, model, _classes, _title = profile_defaults(args.profile)
            settings.profile = args.profile
            settings.remote_workdir = workdir
            settings.remote_binary = binary
            settings.remote_model = model
            if "seg" in args.profile:
                settings.defect_model_kind = "seg"
                settings.remote_defect_model = default_defect_model_for_profile(
                    settings.profile,
                    settings.defect_model_kind,
                )
            else:
                settings.defect_model_kind = "detect"
                settings.remote_defect_model = CHIP_REMOTE_MODEL
        apply_obb_calibration_preset(settings)

    for name in (
        "device",
        "width",
        "height",
        "fps",
        "camera_format",
        "conf",
        "chip_conf",
        "defect_conf",
        "roi_margin",
        "roi_smooth_alpha",
        "roi_hold",
        "chip_interval",
        "defect_confirm",
        "display_max_defects",
        "defect_model_kind",
        "remote_workdir",
        "remote_binary",
        "remote_model",
        "remote_defect_model",
        "adb",
        "serial",
    ):
        value = getattr(args, name)
        if value is not None:
            setattr(settings, name, value)

    if settings.defect_model_kind == "seg" and not settings.remote_defect_model:
        settings.remote_defect_model = default_defect_model_for_profile(
            settings.profile,
            settings.defect_model_kind,
        )
    if settings.defect_model_kind == "detect" and not settings.remote_defect_model:
        settings.remote_defect_model = CHIP_REMOTE_MODEL
    return settings


def _voice_settings_from_args(args: argparse.Namespace, camera_settings: CameraSettings, board_ui: bool) -> VoiceAssistantSettings:
    default_enabled = camera_settings.backend == "local" or board_ui
    enabled = default_enabled if args.voice_assistant is None else bool(args.voice_assistant)
    settings = VoiceAssistantSettings(
        enabled=enabled,
        record_device=args.voice_record_device,
        playback_device=args.voice_playback_device,
        assistant_command=args.voice_command,
        max_threads=max(1, args.voice_threads),
        command_timeout_sec=max(1, args.voice_command_timeout),
    )
    if args.voice_workdir is not None:
        settings.work_dir = args.voice_workdir
    return settings


def _light_settings_from_args(args: argparse.Namespace) -> LightSettings:
    channels = tuple(int(part.strip()) for part in args.light_rgb.split(",", 2))
    if len(channels) != 3:
        raise ValueError("--light-rgb must be R,G,B")
    channels = _normalize_rgb(channels)
    return LightSettings(
        rgb=channels,
        close_rgb=channels,
        high_rgb=channels,
        low_rgb=channels,
        backlight_rgb=channels,
        brightness=args.light_brightness,
        high_brightness=args.light_high_brightness,
        low_brightness=args.light_low_brightness,
        backlight_brightness=args.light_backlight_brightness,
        backlight_count=args.backlight_count,
        backlight_gpio=args.backlight_gpio,
        backlight_gpio_chip=args.backlight_gpio_chip,
        backlight_gpio_line=args.backlight_gpio_line,
        backlight_enabled=not args.no_backlight,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = QApplication([sys.argv[0]])
    camera_settings = _settings_from_args(args)
    window = MainWindow(
        camera_settings,
        board_ui=args.board_ui,
        seg_output_dir=args.output_dir,
        seg_prefix=args.prefix,
        light_settings=_light_settings_from_args(args),
        voice_settings=_voice_settings_from_args(args, camera_settings, args.board_ui),
    )
    app.aboutToQuit.connect(window.shutdown)
    if args.screen_width and args.screen_height:
        window.resize(args.screen_width, args.screen_height)
    if args.window_x or args.window_y:
        window.move(args.window_x, args.window_y)
    if args.fullscreen:
        window.showFullScreen()
    else:
        window.show()
    return app.exec_()

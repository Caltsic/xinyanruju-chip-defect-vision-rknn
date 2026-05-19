# TaishanPi Qt Board GUI

Updated: 2026-05-07

## Summary

Added a board-local PyQt5 GUI launch path for TaishanPi 3M. This keeps the simplified ChipCheck segmentation UI but runs directly on the board with `backend=local`, so frames come from the local RKNN stream process instead of PC ADB transport.

## Code Changes

- `tools/chip_capture_gui/app.py`
  - Added CLI parsing for the PyQt entrypoint.
  - Added `--backend`, `--board-ui`, `--screen-width`, `--screen-height`, `--fullscreen`, and common runtime override arguments.
  - Added compact `800x600` board layout.
  - Changed board layout to a full-screen preview with a collapsed right-side square toggle and semi-transparent floating toolbar.
  - Added `Q/Esc` close shortcut and a board-only `Quit` button.
  - Added Linux font fallback candidates.
  - Enables a chip-only bbox overlay in the live display while keeping defect classes mask/contour-only.
- `tools/chip_capture_gui/__main__.py`
  - Passes CLI args into the PyQt entrypoint.
  - Removes `--board-ui` if PyQt is missing and the app falls back to OpenCV.
- `tools/adb_imx415_rknn_live_view.py`
  - Added a shared `chip_box_overlay` draw option so two-stage segmentation views can show the chip ROI box without restoring defect bboxes.
- `board/desktop/chipcheck-qt-gui`
  - New Qt launcher using `/usr/bin/python3`.
  - Sets X11, font, runtime, and software rendering environment for the HDMI desktop.
  - Uses a safer duplicate-instance check so the launcher does not match its own `pgrep` command.
- `board/desktop/chipcheck-qt.desktop`
  - New desktop launcher for the Qt GUI.

## Board Runtime

Board:

```text
TaishanPi-3M
Debian GNU/Linux 12 bookworm
Linux 6.1.99 aarch64
ADB serial: 2e2609c37dc21c0a
```

Installed dependencies:

```bash
apt-get install -y python3-pyqt5 python3-opencv python3-numpy
```

Direct Debian apt access worked, so the provided proxy subscription was not installed or recorded.

## Deployed Paths

```text
/userdata/chipcheck_vision/tools/chip_capture_gui/
/usr/local/bin/chipcheck-qt-gui
/home/lckfb/Desktop/chipcheck-qt.desktop
/usr/share/applications/chipcheck-qt.desktop
```

Launcher command:

```bash
/usr/bin/python3 -m tools.chip_capture_gui --board-ui --backend local --screen-width 800 --screen-height 600 --window-x 0 --window-y 0 --fullscreen
```

## Verification

System Python imports:

```text
PyQt5 OK
cv2 OK 4.6.0
numpy OK 1.24.2
```

Local backend preflight:

```text
{'camera': True, 'stream': True, 'spidev': True}
```

Short frame read:

```text
frame 0 1280 720 detections 0 fps 0.0
frame 1 1280 720 detections 0 fps 18.5
frame 2 1280 720 detections 0 fps 15.9
```

Qt X11 launcher smoke:

```text
timeout 6s /usr/local/bin/chipcheck-qt-gui
launcher_exit=124
```

No `tools.chip_capture_gui` or `rknn_chip_two_stage` process remained after the timeout test.

Chip-only bbox overlay:

```text
chip_box_off (1, 1, 37422)
chip_box_on  (2, 1, 45158)
ChipCheck Qt True mask-contour
```

Board floating toolbar geometry at 800x600:

```text
collapsed True preview (0, 0, 800, 600) toggle (744, 276, 48, 48) panel_visible False panel (488, 8, 304, 584)
expanded  False preview (0, 0, 800, 600) toggle (434, 14, 48, 48) panel_visible True panel (488, 8, 304, 584)
```

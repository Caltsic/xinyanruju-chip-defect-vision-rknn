# 070 Qt Light Dock RGB Presets

## Context

On 2026-05-13 the Qt GUI needed the lighting controls separated from the right-side control panel. The user wanted a translucent entry at the bottom center of the video image, with per-light brightness, per-light RGB, a default RGB preset, and saved custom lighting presets.

## Implemented Behavior

- The old right-side `Light`, `High Light`, `Low Light`, and `Back Light` sliders were removed from the side panel.
- A semi-transparent `LIGHT` toggle now lives at the bottom center of the preview surface.
- Clicking `LIGHT` opens a compact bottom drawer over the image:
  - preset combo with the built-in `Default RGB 190,255,100`;
  - `Apply`, `Default`, preset-name field, and `Save`;
  - channel selector for `Close Ring`, `High Ring`, `Low Ring`, and `Backlight`;
  - one brightness slider and three RGB sliders for the selected channel;
  - a live swatch showing the selected RGB value.
- Slider edits update `LightSettings` immediately and debounce through the existing WS2812 apply path, so running GUI sessions can adjust light in real time.
- Custom presets persist in `tmp/chip_capture_gui_light_presets.json`.

## Files Changed

- `tools/chip_capture_gui/app.py`
  - Added bottom light dock widgets, positioning, styling, preset load/save, and per-channel editor logic.
  - `_send_light()` now calls `light_controller.apply()` because the GUI state is already in `LightSettings`.
- `tools/chip_capture_gui/settings.py`
  - `LightSettings` now tracks `close_rgb`, `high_rgb`, `low_rgb`, and `backlight_rgb`.
- `tools/chip_capture_gui/ws2812.py`
  - SPI ring command sends `--segment-rgb` for the cascaded 8/12/24 rings.
  - Backlight command sends its independent `backlight_rgb`.
- `board/ws2812/ws2812_spi.py`
  - Added `--segment-rgb` parsing and per-segment RGB scaling.
- `tools/adb_ws2812_ring.py`
  - Deployment/control path forwards segment RGB and independent backlight RGB.
- `board/desktop/chipcheck-qt-gui`
  - Uses `/usr/bin/python3` with `/usr/lib/python3/dist-packages` on `PYTHONPATH`, matching the board's Python 3.11 PyQt5/sip and OpenCV packages.

## Verification

- Local static compile passed:
  - `python -m py_compile tools/chip_capture_gui/app.py tools/chip_capture_gui/settings.py tools/chip_capture_gui/ws2812.py tools/adb_ws2812_ring.py board/ws2812/ws2812_spi.py`
- Qt offscreen smoke instantiated `MainWindow`, toggled the light drawer path, selected `Backlight`, changed RGB to `(12, 34, 56)`, and confirmed `LightSettings.backlight_rgb` updated without starting camera or touching hardware.
- Board import/argument smoke should use `/usr/bin/python3` and system packages:
  - `PYTHONPATH=/usr/lib/python3/dist-packages /usr/bin/python3 ...`
  - Confirmed `PyQt5.QtCore`, `cv2=4.6.0`, and `MainWindow` import work in this environment.

## Notes

- The saved preset file is local runtime state and is intentionally outside source control semantics.
- Board-side GUI sync is required after this change because the Qt code, launcher, and `/userdata/rknn_yolo11_demo/ws2812_spi.py` must all understand the new per-segment RGB path.

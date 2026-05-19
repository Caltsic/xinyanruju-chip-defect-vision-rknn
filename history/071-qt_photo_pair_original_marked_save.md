# 071 Qt Photo Pair Original Marked Save

## Context

On 2026-05-13 the Qt GUI needed a direct photo capture function that saves both the original full-frame image and the marked/annotated image. This is separate from `Save Seg Sample`, which is for CVAT segmentation sample generation.

## Implemented Behavior

- Added `Save Photo Pair` button to the Qt side panel.
- Added `P` keyboard shortcut for the same operation.
- The function saves a paired snapshot under the active GUI output session:

```text
snapshots/original/photo_YYYYMMDD_HHMMSS_mmm_f000001_original.jpg
snapshots/marked/photo_YYYYMMDD_HHMMSS_mmm_f000001_marked.jpg
snapshots/manifest.csv
```

- The original image uses `last_clean_bgr`, the latest clean full-frame camera image.
- The marked image is freshly rendered from the same frame using the current image adjustment and active mask/contour overlay setting. This works even if `Show original frame` is currently checked.
- The manifest records stem, timestamp, frame index, relative image paths, profile, detection counts, image-adjust settings, and light settings.

## Files Changed

- `tools/chip_capture_gui/app.py`
  - Added `Save Photo Pair` button, `save_photo_pair()`, snapshot JPEG writing, manifest append, marked snapshot rendering, and `P` shortcut.
- `tools/chip_capture_gui/README.md`
  - Documented snapshot output layout and shortcut.

## Verification

- Local static compile passed:
  - `python -m py_compile tools/chip_capture_gui/app.py tools/chip_capture_gui/settings.py tools/chip_capture_gui/ws2812.py`
- Qt offscreen smoke instantiated `MainWindow`, injected a synthetic frame, called `save_photo_pair()`, and confirmed one original jpg, one marked jpg, and `snapshots/manifest.csv` were written under `tmp/gui_photo_pair_smoke`.
- Board sync and smoke:
  - Synced `tools/chip_capture_gui` to `/userdata/chipcheck_vision/tools/chip_capture_gui`.
  - Synced launcher fix to `/userdata/chipcheck_vision/board/desktop/chipcheck-qt-gui`.
  - Verified with `PYTHONPATH=/usr/lib/python3/dist-packages /usr/bin/python3 -m py_compile tools/chip_capture_gui/app.py`.
  - Verified `from tools.chip_capture_gui.app import MainWindow` works on the board.
  - Board offscreen smoke injected a synthetic frame and confirmed one original jpg, one marked jpg, and `snapshots/manifest.csv` under `/userdata/chipcheck_vision/tmp/board_photo_pair_smoke`.

## Runtime Environment Note

- The board Qt launcher must use `/usr/bin/python3` with `/usr/lib/python3/dist-packages` on `PYTHONPATH`. The system PyQt5/sip and OpenCV packages are built for Python 3.11. Do not put the miniforge Python 3.13 site-packages ahead of system packages for the Qt GUI launcher.

## Notes

- This is intentionally a full-frame visual record feature. It does not replace `Save Seg Sample` and does not create YOLO labels.

# Seg Mask Labels Restored Without Boxes

## User-Reported Problem

The user clarified that the previous request was only to remove the four-class defect rectangle boxes. It was not intended to remove the segmentation mask class labels.

Observed behavior after the mask-only display change:

- `mask-contour` display no longer showed defect rectangle boxes.
- It also hid the class label text attached to each segmentation mask.
- This made the segmentation result less readable than intended.

## Root Cause

In `tools/adb_imx415_rknn_live_view.py`, label drawing was coupled to the rectangle-box drawing path.

The relevant behavior was:

- `put_label` was only reached when `overlay_draws_boxes(...)` was true.
- The default segmentation overlay mode is `mask-contour`.
- `mask-contour` intentionally disables rectangle boxes.
- Because label rendering was tied to the same branch, disabling boxes also disabled labels.

This was a display-layer bug, not a model or board inference issue.

## Fix

The display logic was changed so labels are controlled independently from rectangle boxes.

Implemented behavior:

- Added or used an `overlay_draws_labels(...)` decision path.
- `mask`, `contour`, `mask-contour`, `all`, and `boxes` can draw class labels.
- Rectangle boxes are still drawn only when `overlay_draws_boxes(...)` is true.
- `mask-contour` now means: masks + contours + labels, no rectangle boxes.
- `boxes` remains useful for debug-style rectangle and label display.
- `all` remains full debug display: masks, contours, boxes, and labels.

Related UI and documentation wording was aligned:

- GUI text changed from `Draw boxes/labels` to `Draw boxes`.
- `README.md` and `tools/chip_capture_gui/README.md` now describe `mask-contour` as displaying masks, contours, and labels without rectangle boxes.

## Verification

Verification recorded for this fix:

- Python compile check passed with `py_compile`.
- Local drawing regression confirmed that `mask-contour` shows the class label.
- Local drawing regression confirmed that the bbox left-edge probe remained `0`, meaning no rectangle border was drawn.
- Board headless 45-frame check saved:
  - `captures/seg_mask_label_no_box_check.jpg`
- The board screenshot showed:
  - `scratch` label visible.
  - Segmentation contour visible.
  - No defect rectangle box visible.

## Current Intended Runtime Semantics

For normal segmentation live view:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

Default behavior for the segmentation profile:

- Shows segmentation masks.
- Shows segmentation contours.
- Shows class labels.
- Does not show rectangular defect boxes.

For debug display with boxes and scores:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-seg-imx678 --overlay-mode all --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

## Residual Risk

No remaining known display defect from this issue. The important distinction for future changes is:

- Removing rectangle boxes must not imply removing mask labels.
- Label visibility and box visibility should stay independently controlled in the overlay logic.

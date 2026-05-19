# OBB实时窗口与GUI链路不一致导致chip框不跟芯片

Updated: 2026-05-11

## Problem

User reported that the realtime `chip` OBB frame did not follow the chip, despite the latest OBB chip model already being trained and deployed.

## Verified Model Version

The deployed chip OBB model was not stale.

Current board chip model:

```text
/userdata/rknn_yolo11_demo/model/chip_roi_yolov8_obb_split_int8.rknn
sha256 = 8a12a0abd2dfe7f813701aba0096a7a6643767fd197c90a7eea3b4ffbe502c6b
```

This matches the local trained artifact:

```text
cloud_training/chip_roi_yolov8_rknn/outputs_obb_cvat_20260509/final/chip_roi_yolov8_obb_split_int8.rknn
```

So the issue was not “wrong chip weights pushed to board”.

## Root Cause

The visible good behavior seen earlier came from the GUI/capture path, not from the plain realtime command path.

There were two important mismatches:

1. GUI path applied image-side OBB geometric refinement:

```text
tools/chip_capture_gui/obb_refine.py
```

That refinement uses thresholding + contour extraction + `minAreaRect` to tighten the chip box around the actual chip geometry.

2. Plain realtime command path did not apply that refinement, and also still used generic two-stage defaults that were too conservative for OBB:

```text
chip_conf = 0.25
roi_smooth_alpha = 0.35
roi_hold = 3
chip_interval = 3
```

The GUI OBB preset instead used:

```text
chip_conf = 0.45
roi_smooth_alpha = 0.55
roi_hold = 1
chip_interval = 1
```

So the earlier “good OBB” and the normal live window were not actually running equivalent logic.

## Fix

Updated file:

```text
tools/adb_imx415_rknn_live_view.py
```

Changes:

1. Added local OBB image refinement for profile:

```text
chip-two-stage-obb-seg-imx678
```

This reuses the same practical logic as the GUI path:

- threshold
- morphology
- contour selection
- `minAreaRect`
- ordered 4-point OBB replacement

2. Aligned the plain live-view OBB profile defaults with the GUI OBB preset when the user does not override them:

```text
chip_conf -> 0.45
roi_smooth_alpha -> 0.55
roi_hold -> 1
chip_interval -> 1
```

3. Disabled extra PC-side EMA lag for the chip class itself by forcing class `0` overlay updates to use the latest box directly.

Defect smoothing remains unchanged.

## Verification

Ran realtime board test after the fix:

```text
F:\anaconda\python.exe tools/adb_imx415_rknn_live_view.py --profile chip-two-stage-obb-seg-imx678 --headless --frames 40 --save-snapshot tmp/obb_recheck_20260511.jpg --save-clean-snapshot tmp/obb_recheck_20260511_clean.jpg
```

Observed:

```text
Processed frames: 40
det present from frame 0 onward
```

Snapshot:

```text
tmp/obb_recheck_20260511.jpg
```

Result:

- chip OBB now follows the chip body correctly in the realtime window
- defect overlay is present on the same frame

## Important Scope Note

This fix aligned the plain PC live-view path with the GUI path and removed the visible OBB mismatch that triggered the report.

The board two-stage C++ binary still fundamentally generates the chip ROI from its own onboard OBB result. The new PC-side refinement fixes the displayed live-view geometry and keeps the operator-facing behavior consistent with the GUI path.

If future work requires the board-side rotated crop itself to use the same geometric refinement before second-stage defect inference, that needs a separate native C++ runtime refinement step inside:

```text
rknn_work/board_yolo11_src/examples/yolo11/cpp/live_camera_yolo.cc
```

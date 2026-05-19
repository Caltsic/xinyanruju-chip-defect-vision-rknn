# Chip OBB Manual Annotation Training, RKNN Deployment, And Channel Order Fix

Updated: 2026-05-09

## Summary

This archive records the full CVAT project-export based chip ROI OBB training run, RKNN conversion, board deployment, and the output-channel order bug fix that restored rotated OBB boxes in the live board stream.

No SSH passwords, ports, tokens, IP credentials, or hidden credentials are recorded here.

## Dataset Source And Conversion

Source was a CVAT project-level export for chip ROI OBB annotation.

Conversion statistics:

```text
images=2956
objects=2897
empty_images=59
non_4_point_polygons=2
```

The two 5-point polygons were dropped per user instruction.

All 4-point polygons were regularized with OpenCV `minAreaRect` and converted to YOLO OBB format.

## Cloud Training Result

Cloud training ran on RTX5090 with YOLOv8n-OBB for 220 epochs.

Final epoch 220:

```text
P=0.996500
R=0.999770
mAP50=0.995000
mAP50-95=0.987010
```

Best epoch 208:

```text
P=0.996290
R=1.000000
mAP50=0.994970
mAP50-95=0.987400
```

## Training Dependency Fix

The cloud base environment was missing:

```text
onnxscript
onnx_ir
```

These were installed on the cloud host. The training package requirements were also updated:

```text
cloud_training/chip_roi_yolov8_rknn/requirements.txt
onnxscript>=0.3
onnx_ir>=0.1.12
```

## RKNN Conversion Dependency Fix

The `rknn232` environment originally had `onnx 1.21.0`, which no longer exposed `onnx.mapping` as expected by RKNN-Toolkit2.

Downgrading ONNX to `onnx 1.16.1` allowed RKNN-Toolkit2 `2.3.2` to load the exported ONNX successfully.

## Critical Channel Order Bug

Root cause:

Ultralytics YOLOv8-OBB ONNX export uses channel order:

```text
xywh + class score + angle
```

The original splitter and board-side C++ fallback decoder incorrectly assumed:

```text
xywh + angle + score
```

Observed symptom:

The board snapshot showed `chip 1.00`, but the OBB box was shifted left / abnormal.

Fixed files:

```text
tools/split_yolov8_obb_onnx_outputs.py
rknn_work/board_yolo11_src/examples/yolo11/cpp/postprocess.cc
```

Splitter fix:

```text
boxes = channels 0:4
scores = channels 4:4+class_count
angle = channels 4+class_count:5+class_count
```

The split model output order remains:

```text
boxes, angle, scores
```

Board C++ fix:

`postprocess.cc` single-output OBB fallback decoding now matches Ultralytics YOLOv8-OBB channel order.

## Regenerated Artifacts

After the channel-order fix, ONNX was split again and both FP and INT8 RKNN artifacts were regenerated.

Local final artifact directory:

```text
cloud_training/chip_roi_yolov8_rknn/outputs_obb_cvat_20260509/final/
```

Key files:

| File | Size |
| --- | ---: |
| `chip_roi_yolov8_obb.pt` | 7,770,579 bytes |
| `chip_roi_yolov8_obb_split.onnx` | 12,797,807 bytes |
| `chip_roi_yolov8_obb_fp.rknn` | 13,567,263 bytes |
| `chip_roi_yolov8_obb_split_int8.rknn` | 10,577,363 bytes |

Conversion report:

```text
rknn_conversion_report.json
using_split_onnx=true
target=rk3576
RKNN-Toolkit2=2.3.2
```

## Board Deployment

Corrected INT8 model was pushed to:

```text
/userdata/rknn_yolo11_demo/model/chip_roi_yolov8_obb_split_int8.rknn
```

The wrong channel-order version was backed up on the board as:

```text
/userdata/rknn_yolo11_demo/model/chip_roi_yolov8_obb_split_int8.rknn.bak_wrong_order_20260509
```

## Board Verification

Headless live-view verification passed for 30 frames with:

```text
adb_imx415_rknn_live_view.py --profile chip-two-stage-obb-seg-imx678 ...
```

Observed after the resplit fix:

```text
frames=30
fps=about 8
det=1/1
```

Snapshot:

```text
tmp/obb_seg_after_resplit_snapshot.jpg
```

Snapshot result:

The rotated OBB recovered. The current box covers the chip and pins but is wider than ideal. If tighter geometry is required later, optimize the manual annotation boundary / ROI definition rather than treating this as a runtime decoding problem.

## Recommended Real-Time Window Command

Use this command shape for the current OBB + segmentation live window:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-obb-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

## Follow-Up Notes

- Keep the split ONNX/RKNN channel order contract as `boxes, angle, scores` even though the original Ultralytics ONNX source is `xywh + scores + angle`.
- For future OBB model exports, verify the channel order before trusting board-side geometry.
- If live OBB appears confident but spatially wrong again, first check splitter/C++ channel interpretation and regenerated RKNN provenance.
- Current OBB quality is functionally restored, but box tightness depends on the manual annotation target definition.

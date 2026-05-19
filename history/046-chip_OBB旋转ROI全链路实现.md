# Chip OBB Rotated ROI Full Pipeline

Updated: 2026-05-09

## Summary

This task added an opt-in chip OBB path across dataset preparation, YOLOv8-OBB training/RKNN conversion, board-side C++ inference/postprocess, rotated ROI cropping, PC live-view protocol parsing, GUI profile selection, and GUI segmentation sample capture. The regular segmentation profile remains the default; OBB is selected explicitly with `chip-two-stage-obb-seg-imx678`.

## Dataset And Training Scripts

New OBB scripts under `cloud_training/chip_roi_yolov8_rknn/scripts/`:

- `prepare_obb_dataset.py`
  - Converts the existing one-class chip ROI YOLO HBB dataset from 5-column labels:
    `class cx cy w h`
    into YOLO OBB 9-column labels:
    `class x1 y1 x2 y2 x3 y3 x4 y4`.
  - Estimates a rotated chip rectangle near each HBB crop with OpenCV `minAreaRect`.
  - Falls back to the horizontal box represented as 4 points when no stable contour is found, so valid HBB objects remain trainable.
  - Writes `data.yaml`, `chip_roi_labels.txt`, `calib_dataset.txt`, `dataset_report.json`, optional preview images, and supports `--self-check`.
  - Default class list remains one class: `0 chip`.
- `train_yolov8_obb.py`
  - Uses Ultralytics `YOLO(...).train(task="obb", ...)`.
  - Defaults: `yolov8n-obb.pt`, `imgsz=640`, `epochs=200`, `batch=-1`, `device=0`, `patience=50`.
  - Can copy `best.pt` to a stable final destination.
- `run_obb.py`
  - Runs prepare -> train or reuse `--weights` -> ONNX export -> split ONNX -> RKNN conversion.
  - Final output directory default: `outputs_obb/final/`.
  - Expected stable artifacts:
    - `chip_roi_yolov8_obb.pt`
    - `chip_roi_yolov8_obb.onnx`
    - `chip_roi_yolov8_obb_split.onnx`
    - `chip_roi_yolov8_obb_fp.rknn`
    - `chip_roi_yolov8_obb_split_int8.rknn`
    - `chip_roi_labels.txt`
    - `calib_dataset.txt`
    - `dataset_report.json`

New helper:

- `tools/split_yolov8_obb_onnx_outputs.py`
  - Splits a standard YOLOv8-OBB ONNX output into `yolov8_obb_boxes`, `yolov8_obb_angle`, and `yolov8_obb_scores`.
  - Infers channel axis from the 3D output shape.
  - Infers class count as `channel_count - 5` unless `--class-count` is supplied.

RKNN conversion update:

- `cloud_training/chip_roi_yolov8_rknn/scripts/convert_rknn.py`
  - Added `--split-onnx`.
  - Prefers an explicit split ONNX, or `*_split.onnx` beside the requested ONNX if present.
  - Writes report fields `onnx_requested`, `onnx_used`, and `using_split_onnx`.
  - Names INT8 output `*_split_int8.rknn` when using split ONNX, otherwise keeps `*_int8.rknn`.

README entry:

```bash
python scripts/run_obb.py \
  --raw-dataset dataset_raw/chip_roi_yolo \
  --work-dir outputs_obb \
  --model yolov8n-obb.pt \
  --imgsz 640 \
  --epochs 200 \
  --batch 64 \
  --device 0 \
  --overwrite-dataset
```

## Dataset Smoke Result

Local OBB prepare smoke output:

```text
tmp/obb_prepare_smoke/dataset_report.json
tmp/obb_prepare_smoke_calib.txt
tmp/obb_prepare_smoke_labels.txt
tmp/obb_prepare_smoke/preview/{train,valid,test}/...
```

Report facts from `tmp/obb_prepare_smoke/dataset_report.json`:

```text
source: chip_roi/generated/cloud_chip_roi_yolo
output: tmp/obb_prepare_smoke
format: yolo_obb_8point
source_format: yolo_hbb_5column
image_mode: hardlink
class_names: ["chip"]
obb method: opencv_minAreaRect_near_hbb_crop
fallback: horizontal_four_points
padding_ratio: 0.18
min_contour_area_ratio: 0.18
```

Split counts:

```text
train: images=964, labels=964, objects=915, auto_rects=915, fallback_rects=0, empty_label_files=49
valid: images=111, labels=111, objects=111, auto_rects=111, fallback_rects=0, empty_label_files=0
test:  images=103, labels=103, objects=103, auto_rects=103, fallback_rects=0, empty_label_files=0
self_check: checked_label_files=1178, checked_objects=1129
preview: train=2, valid=2, test=2
```

This validates the HBB -> OBB dataset conversion and label self-check on the current chip ROI dataset. It does not prove OBB training quality or board runtime quality.

## Board C++ OBB Runtime

Touched board-side C++ files:

- `rknn_work/board_yolo11_src/examples/yolo11/cpp/live_camera_yolo.cc`
- `rknn_work/board_yolo11_src/examples/yolo11/cpp/postprocess.cc`
- `rknn_work/board_yolo11_src/examples/yolo11/cpp/postprocess.h`
- `rknn_work/board_yolo11_src/examples/yolo11/cpp/rknpu2/yolo11.cc`
- `rknn_work/board_yolo11_src/examples/yolo11/cpp/yolo11.h`

Runtime model kind additions:

- Added `YOLO_MODEL_KIND_OBB`.
- Added CLI `--chip-model-kind detect|obb`; aliases accepted in parser include `obb`, `rotated`, and `oriented`.
- Default OBB chip model path in board binary:

```text
model/chip_roi_yolov8_obb_split_int8.rknn
```

OBB inference/postprocess:

- Added `object_obb_point`, `object_obb_result`, and `object_obb_result_list`.
- Added `inference_yolo11_obb_model(...)`.
- Added `post_process_obb(...)`.
- Supports:
  - single-output YOLOv8-OBB tensor with channels `4 + 1 angle + classes`;
  - split-output tensors with boxes, angle, and scores.
- Maps letterboxed model-space OBB points back to source frame coordinates.
- Produces an AABB fallback box from OBB points so the existing detection list can still carry the chip entry.

Rotated ROI crop:

- Added OBB geometry refresh/sanitize and temporal smoothing/hold helpers.
- Added rotated RGB crop path `crop_rgb_obb(...)`.
- Uses affine transform for OBB crop -> source mapping.
- When the chip model is OBB, defect detection/segmentation runs on the rotated chip crop instead of only the horizontal AABB crop.
- Defect bbox and seg contour outputs are mapped back from crop coordinates into full-frame coordinates through the affine transform.
- Detect profile still uses the previous HBB crop path.

Streaming protocol behavior:

- Existing bbox-only RYL1 detection records remain unchanged.
- Existing contour flag remains:

```text
DETECTION_CONTOURS_FLAG = 0x80000000
```

- Board can stream the chip OBB as a 4-point contour for class `chip` alongside defect seg contours via a mixed contour block.
- PC code also reserves an explicit OBB sidecar flag for future/alternate board streams:

```text
DETECTION_OBB_FLAG = 0x40000000
```

## PC Live View And Profile

Touched PC live-view file:

- `tools/adb_imx415_rknn_live_view.py`

New constants and parsing:

- `OBB_STRUCT = <fffffffff`
- `DETECTION_OBB_FLAG = 0x40000000`
- `CHIP_ROI_OBB_REMOTE_MODEL = model/chip_roi_yolov8_obb_split_int8.rknn`
- `Detection` and smoothing tracks now carry:
  - `obb_points`
  - `obb_angle`
- Added OBB sidecar parser. One record per detection:

```text
x0,y0,x1,y1,x2,y2,x3,y3,angle as float32
```

Compatibility path:

- If the board sends explicit OBB sidecar data, PC attaches it to the matching detection.
- If the board sends a 4-point contour for class `chip`, PC treats that contour as chip OBB points.
- Old streams without OBB flag continue through the previous bbox/contour parser.

New opt-in profile:

```bash
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-obb-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

Profile behavior:

- Board binary remains `rknn_chip_two_stage_maixcam_stream`.
- Chip model kind passed to board becomes `obb`.
- Defect model kind remains `seg`.
- Overlay default for seg profiles remains `mask-contour`.
- Chip-only overlay draws the rotated box when OBB points are available.
- Defect classes continue to display masks/contours and labels without restoring defect rectangles in the default seg view.

## GUI Profile And OBB Crop Capture

Touched GUI files:

- `tools/chip_capture_gui/README.md`
- `tools/chip_capture_gui/app.py`
- `tools/chip_capture_gui/opencv_app.py`
- `tools/chip_capture_gui/settings.py`
- `tools/chip_capture_gui/seg_sample.py`
- `tools/chip_capture_gui/__main__.py`

Profile/default changes:

- Default GUI profile is still `chip-two-stage-seg-imx678`.
- Added profile selector option:

```text
chip-two-stage-obb-seg-imx678
```

- CLI can pass `--profile chip-two-stage-obb-seg-imx678`.
- OBB is explicitly opt-in to avoid changing the existing segmentation workflow.

GUI capture behavior:

- `SegSampleWriter` now first tries to find a chip OBB from detections.
- If chip OBB is present:
  - computes rotated crop dimensions from the OBB edge lengths and `roi_margin`;
  - uses affine warp to save an upright chip crop;
  - maps defect prelabels from full-frame coordinates into rotated crop coordinates;
  - writes metadata with `crop_mode: "obb"`, `crop_obb_points`, `crop_to_full_affine`, and `full_to_crop_affine`.
- If no usable OBB is present, capture falls back to the existing HBB chip crop path.
- If no chip ROI is detected at all, no sample is saved.

Segmentation sample output structure remains:

```text
chip_seg/captures/gui_session_YYYYMMDD_HHMMSS/
  images/
  labels/
  images_full/
  previews/
  meta/
  manifest.csv
```

## Documentation Updates

Updated docs include:

- `README.md`
  - Added the OBB-compatible profile command.
  - Documented RYL1 compatibility, `DETECTION_OBB_FLAG`, and 4-point chip contour fallback.
  - Clarified that normal seg profile remains default.
- `cloud_training/chip_roi_yolov8_rknn/README.md`
  - Added OBB training variant and final artifact expectations.
- `tools/chip_capture_gui/README.md`
  - Added GUI profile selector note for OBB seg.
  - Documented that OBB profile keeps `mask-contour` and uses OBB sidecar or 4-point chip contour for chip rotated box.

## Verification Commands And Results

Observed local dataset conversion result:

```text
tmp/obb_prepare_smoke/dataset_report.json
```

Result:

```text
1178 label files checked
1129 OBB objects checked
0 fallback rects
6 preview images written
```

Relevant command shape for reproducing the dataset smoke:

```bash
python cloud_training/chip_roi_yolov8_rknn/scripts/prepare_obb_dataset.py \
  --raw-dataset chip_roi/generated/cloud_chip_roi_yolo \
  --output-dir tmp/obb_prepare_smoke \
  --calib-output tmp/obb_prepare_smoke_calib.txt \
  --labels-output tmp/obb_prepare_smoke_labels.txt \
  --preview-count 2 \
  --self-check \
  --overwrite
```

Full OBB train/export/RKNN command shape:

```bash
cd cloud_training/chip_roi_yolov8_rknn
python scripts/run_obb.py \
  --raw-dataset dataset_raw/chip_roi_yolo \
  --work-dir outputs_obb \
  --model yolov8n-obb.pt \
  --imgsz 640 \
  --epochs 200 \
  --batch 64 \
  --device 0 \
  --overwrite-dataset
```

PC live OBB profile command shape:

```bash
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-obb-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

Current verified facts in this archive are implementation/static-context plus dataset conversion smoke. No completed board-side OBB RKNN live smoke result was found in the visible working context.

## Follow-Up Notes

- Train or reuse a real YOLOv8-OBB chip model, export split ONNX, convert `chip_roi_yolov8_obb_split_int8.rknn`, and deploy it to:

```text
/userdata/rknn_yolo11_demo/model/chip_roi_yolov8_obb_split_int8.rknn
```

- Rebuild and deploy the updated board stream binary before expecting `--chip-model-kind obb` to work on the board.
- Run a board smoke test for `chip-two-stage-obb-seg-imx678` and record FPS, status-bar `det raw/drawn`, screenshots, and any contour/OBB parser errors.
- Compare rotated ROI crop quality against the existing HBB crop path on real slanted chips; OBB crop may improve alignment but can also expose angle jitter if the chip OBB model is unstable.
- Keep default production observation on `chip-two-stage-seg-imx678` until OBB model quality and board stability are proven.
- When capturing segmentation samples, inspect `meta/*.json` for `crop_mode` to confirm whether a given sample came from OBB or HBB fallback.

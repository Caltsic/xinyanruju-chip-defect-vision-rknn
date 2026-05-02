# Chip Defect YOLOv8 + RK3576 RKNN Cloud Package Plan

## Summary

Build a cloud-runnable package that trains a YOLOv8 detection model from the semiconductor chip defect dataset, exports a Rockchip-friendly ONNX model, and converts it to both FP and INT8 RKNN for RK3576.

INT8 is the board deployment target. FP is retained as the baseline and debugging model.

## Key Changes

- Use YOLOv8 detect for the first board-ready version.
- Convert mixed YOLO polygon/bbox labels into a separate bbox-only detection dataset.
- Keep raw dataset labels unchanged.
- Fix the data config to local splits: `train/images`, `valid/images`, `test/images`.
- Use four classes: `ZF-scratch`, `scratch`, `broken`, `pinbreak`.
- Export both `chipcheck_yolov8_detect_fp.rknn` and `chipcheck_yolov8_detect_int8.rknn`.
- Generate `calib_dataset.txt` from representative training images for INT8 quantization.

## Implementation

- Cloud package source: `cloud_training/yolov8_rknn/`
- Dataset conversion: `scripts/prepare_dataset.py`
- Training: `scripts/train_yolov8.py`
- Rockchip ONNX export: `scripts/export_onnx.py`
- RKNN FP/INT8 conversion: `scripts/convert_rknn.py`
- One-command pipeline: `scripts/run_all.py`
- RKNN Toolkit2 helper: `scripts/install_rknn_toolkit2.py`

The upload zip should include the package source and the raw dataset under `dataset_raw/chip_defect_raw/` with ASCII paths.

## Test Plan

- Run dataset preparation against the local dataset and confirm image/label pairing, class IDs, bbox bounds, and calibration list.
- Compile Python scripts with `py_compile`.
- On cloud GPU, run at least a short epoch smoke test before full training.
- Export ONNX using Rockchip's YOLOv8 fork.
- Convert both FP and INT8 RKNN with `target_platform=rk3576`.
- Compare FP and INT8 predictions before deploying INT8 to the board.

## Assumptions

- First version is detection boxes only, not segmentation masks.
- Default model is `yolov8n.pt` at `640x640`.
- If `yolov8n` accuracy is insufficient, train `yolov8s.pt` as a second candidate.
- Board deployment will use YOLOv8 RKNN C++ postprocess, not the current YOLO11 hard-coded postprocess.

# Chip Defect YOLOv8 RKNN Cloud Package

This package trains a YOLOv8 detection model for four semiconductor chip defect classes, exports a Rockchip-friendly ONNX model, and converts it to both FP and INT8 RKNN for RK3576.

## Inputs

The packaged zip uses this ASCII dataset path:

```text
dataset_raw/chip_defect_raw/
  train/images + train/labels
  valid/images + valid/labels
  test/images  + test/labels
```

The raw labels are mixed YOLO bbox and YOLO polygon labels. `scripts/prepare_dataset.py` creates a separate detection-only dataset by converting polygons to bounding boxes. Raw labels are not overwritten.

Classes:

```text
0 ZF-scratch
1 scratch
2 broken
3 pinbreak
```

## Cloud Run

Use an isolated Linux Python environment. Python 3.10 is the safest choice for RKNN-Toolkit2 wheels.

```bash
cd chipcheck_yolov8_rknn
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install "setuptools==69.5.1"
python -m pip install -r requirements.txt

# Required for RKNN conversion. Skip this only if rknn-toolkit2 is already installed.
python scripts/install_rknn_toolkit2.py --third-party-dir third_party

python scripts/run_all.py \
  --raw-dataset dataset_raw/chip_defect_raw \
  --work-dir outputs \
  --model yolov8n.pt \
  --imgsz 640 \
  --epochs 150 \
  --device 0
```

If the cloud image cannot install RKNN-Toolkit2, run the same command with `--skip-rknn` to produce `best.pt` and ONNX first, then run `scripts/convert_rknn.py` in a compatible RKNN environment.

## Final Artifacts

Expected final directory:

```text
outputs/final/
  chipcheck_yolov8_detect.pt
  chipcheck_yolov8_detect.onnx
  chipcheck_yolov8_detect_fp.rknn
  chipcheck_yolov8_detect_int8.rknn
  chip_defect_labels.txt
  calib_dataset.txt
  dataset_report.json
  rknn/rknn_conversion_report.json
```

INT8 is the board-side deployment target. FP is kept as the baseline model for structure checks and debugging.

## Important RK3576 Notes

- ONNX export defaults to Rockchip's `airockchip/ultralytics_yolov8` fork because it moves YOLOv8 DFL/post-processing work outside the model and is intended for RKNPU deployment.
- RKNN conversion uses `target_platform=rk3576`, `mean_values=[[0,0,0]]`, and `std_values=[[255,255,255]]`, matching Rockchip model-zoo YOLOv8 conversion.
- INT8 conversion uses `outputs/calib_dataset.txt`, generated from train images. It contains image paths only, not labels.
- The current project board program is a YOLO11 live stream demo. Do not directly replace its model with this YOLOv8 RKNN. Use or port Rockchip's YOLOv8 C++ postprocess and set the class count to 4.

Official references:

- https://github.com/airockchip/rknn_model_zoo
- https://github.com/airockchip/ultralytics_yolov8
- https://github.com/airockchip/rknn-toolkit2
- https://wiki.lckfb.com/en/tspi-3-rk3576/ai/yolov8/detection-model.html

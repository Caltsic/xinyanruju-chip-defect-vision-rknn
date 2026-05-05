# Chip ROI YOLOv8 RKNN Cloud Package

This package trains a one-class YOLOv8 detector for locating the whole chip
body, exports a Rockchip-friendly ONNX model, and converts it to FP and INT8
RKNN for RK3576.

## Dataset

The upload zip contains an already prepared YOLO dataset:

```text
dataset_raw/chip_roi_yolo/
  train/images + train/labels
  valid/images + valid/labels
  test/images  + test/labels
```

Class:

```text
0 chip
```

Negative samples are included as images with empty `.txt` label files.

## Cloud Run

Use the rented Ubuntu 22.04 / Python 3.12 / CUDA environment. Training can use
the existing PyTorch 2.8 environment. RKNN conversion may install RKNN-Toolkit2
into the same or a separate virtual environment; the current project has
already verified RKNN-Toolkit2 2.3.2 on Python 3.12.

```bash
cd chip_roi_yolov8_rknn
python -m pip install --upgrade pip wheel
python -m pip install "setuptools==69.5.1"
python -m pip install -r requirements.txt

# Train and export ONNX first, before installing RKNN-Toolkit2. Some RKNN wheels
# install their own dependency set, so this order preserves the cloud PyTorch/CUDA
# training environment.
python scripts/run_all.py \
  --raw-dataset dataset_raw/chip_roi_yolo \
  --work-dir outputs \
  --model /root/autodl-tmp/chip_roi_train_20260504/yolov8n.pt \
  --imgsz 640 \
  --epochs 200 \
  --batch 64 \
  --device 0 \
  --overwrite-dataset \
  --skip-rknn

# Then install RKNN-Toolkit2 in a separate environment and convert the exported
# ONNX to FP/INT8 RKNN. The ONNX pin is required for RKNN-Toolkit2 2.3.2.
python -m venv ../rknn_env
../rknn_env/bin/python -m pip install --upgrade pip wheel "setuptools==69.5.1"
../rknn_env/bin/python scripts/install_rknn_toolkit2.py \
  --method pypi \
  --version 2.3.2 \
  --pin-onnx 1.16.1
../rknn_env/bin/python scripts/convert_rknn.py \
  --onnx outputs/final/chip_roi_yolov8_detect.onnx \
  --output-dir outputs/final/rknn \
  --calib-dataset outputs/calib_dataset.txt \
  --target-platform rk3576 \
  --name chip_roi_yolov8_detect
cp -f outputs/final/rknn/chip_roi_yolov8_detect_fp.rknn outputs/final/
cp -f outputs/final/rknn/chip_roi_yolov8_detect_int8.rknn outputs/final/
```

If the environment already has a known-good RKNN-Toolkit2 installation and it
does not disturb PyTorch/CUDA training, `scripts/run_all.py` can be run without
`--skip-rknn`.

If the cloud cannot download `yolov8n.pt` reliably, upload a known-good local
copy first and pass its absolute path to `--model`. A partial 303 KB
`yolov8n.pt` was observed to stall training initialization.

## Final Artifacts

Expected final directory:

```text
outputs/final/
  chip_roi_yolov8_detect.pt
  chip_roi_yolov8_detect.onnx
  chip_roi_yolov8_detect_fp.rknn
  chip_roi_yolov8_detect_int8.rknn
  chip_roi_labels.txt
  calib_dataset.txt
  dataset_report.json
  rknn/rknn_conversion_report.json
```

`chip_roi_yolov8_detect_int8.rknn` is the board-side deployment target. Keep the
FP RKNN and ONNX as debug baselines.

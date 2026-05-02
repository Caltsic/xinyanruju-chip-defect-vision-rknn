#!/usr/bin/env bash
set -euo pipefail
export PYTHONIOENCODING=utf-8
export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export TMPDIR=/root/autodl-tmp/tmp
cd /root/autodl-tmp/chipcheck_yolov8_rknn
RKPY=/root/autodl-tmp/rknn_env/bin/python
$RKPY scripts/convert_rknn.py \
  --onnx outputs/final/chipcheck_yolov8_detect.onnx \
  --output-dir outputs/final/rknn \
  --calib-dataset outputs/calib_dataset.txt \
  --target-platform rk3576 \
  --name chipcheck_yolov8_detect
cp outputs/final/rknn/chipcheck_yolov8_detect_fp.rknn outputs/final/
cp outputs/final/rknn/chipcheck_yolov8_detect_int8.rknn outputs/final/

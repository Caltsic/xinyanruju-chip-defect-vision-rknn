#!/usr/bin/env bash
set -euo pipefail
export PYTHONIOENCODING=utf-8
export LC_ALL=C.UTF-8
export LANG=C.UTF-8
PY=/root/miniconda3/bin/python
rm -rf outputs
$PY scripts/run_all.py \
  --raw-dataset dataset_raw/chip_defect_raw \
  --work-dir outputs \
  --model yolov8n.pt \
  --imgsz 640 \
  --epochs 150 \
  --batch 64 \
  --device 0 \
  --workers 8 \
  --skip-rknn \
  --overwrite-dataset \
  --standard-export-fallback

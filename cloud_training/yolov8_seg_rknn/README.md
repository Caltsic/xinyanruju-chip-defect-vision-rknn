# Chip Defect YOLOv8-Seg RKNN Cloud Package

This independent package trains a YOLOv8 segmentation model, exports ONNX with
stable artifact names, splits the segmentation outputs for RKNN quantization,
and converts FP/INT8 RKNN models for RK3576.

It does not modify or depend on the existing `cloud_training/yolov8_rknn`
detection package.

## Dataset

Expected input layout:

```text
dataset_raw/chip_defect_raw/
  train/images + train/labels
  valid/images + valid/labels
  test/images  + test/labels
```

YOLO segmentation labels are preserved as polygon rows:

```text
class_id x1 y1 x2 y2 x3 y3 ...
```

BBox-only rows (`class cx cy w h`) are skipped by default. Images with no
remaining polygon object are skipped and listed in `dataset_report.json`. Pass
`--keep-empty-images` only when you intentionally want negative images.

Default classes:

```text
0 ZF-scratch
1 scratch
2 broken
3 pinbreak
```

## Install

```bash
cd yolov8_seg_rknn
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install "setuptools==69.5.1"
python -m pip install -r requirements.txt
```

## Full Pipeline

Train, export, split ONNX, and convert RKNN in one environment:

```bash
python scripts/run_all.py \
  --raw-dataset dataset_raw/chip_defect_raw \
  --work-dir outputs \
  --model yolov8n-seg.pt \
  --imgsz 640 \
  --epochs 150 \
  --batch -1 \
  --device 0 \
  --overwrite-dataset
```

On many cloud images it is safer to train/export first, then convert in a
separate RKNN-Toolkit2 environment:

```bash
python scripts/run_all.py \
  --raw-dataset dataset_raw/chip_defect_raw \
  --work-dir outputs \
  --model yolov8n-seg.pt \
  --imgsz 640 \
  --epochs 150 \
  --device 0 \
  --overwrite-dataset \
  --skip-rknn

python -m venv ../rknn_env
../rknn_env/bin/python -m pip install --upgrade pip wheel "setuptools==69.5.1"
../rknn_env/bin/python scripts/install_rknn_toolkit2.py --third-party-dir third_party
../rknn_env/bin/python scripts/convert_rknn.py \
  --onnx outputs/final/chipcheck_yolov8_seg.onnx \
  --split-onnx outputs/final/chipcheck_yolov8_seg_split.onnx \
  --output-dir outputs/final/rknn \
  --calib-dataset outputs/calib_dataset.txt \
  --target-platform rk3576 \
  --name chipcheck_yolov8_seg
cp -f outputs/final/rknn/chipcheck_yolov8_seg_fp.rknn outputs/final/
cp -f outputs/final/rknn/chipcheck_yolov8_seg_split_int8.rknn outputs/final/
```

## Step Commands

Prepare segmentation dataset:

```bash
python scripts/prepare_dataset.py \
  --raw-dataset dataset_raw/chip_defect_raw \
  --output-dir outputs/dataset_yolov8_seg \
  --calib-output outputs/calib_dataset.txt \
  --labels-output outputs/chip_defect_seg_labels.txt \
  --overwrite
```

Train:

```bash
python scripts/train_yolov8.py \
  --data outputs/dataset_yolov8_seg/data.yaml \
  --output-dir outputs/train \
  --model yolov8n-seg.pt \
  --name chipcheck_yolov8_seg \
  --imgsz 640 \
  --epochs 150 \
  --device 0 \
  --copy-best-to outputs/final/chipcheck_yolov8_seg.pt
```

Export ONNX:

```bash
python scripts/export_onnx.py \
  --weights outputs/final/chipcheck_yolov8_seg.pt \
  --output outputs/final/chipcheck_yolov8_seg.onnx \
  --imgsz 640 \
  --opset 12 \
  --auto-clone \
  --install-fork \
  --standard-fallback
```

Diagnose and split ONNX outputs:

```bash
python ../../tools/diagnose_yolov8_seg_onnx.py \
  --model outputs/final/chipcheck_yolov8_seg.onnx \
  --class-count 4 \
  --mask-count 32

python ../../tools/split_yolov8_seg_onnx_outputs.py \
  --input outputs/final/chipcheck_yolov8_seg.onnx \
  --output outputs/final/chipcheck_yolov8_seg_split.onnx \
  --class-count 4 \
  --mask-count 32
```

Convert RKNN:

```bash
python scripts/convert_rknn.py \
  --onnx outputs/final/chipcheck_yolov8_seg.onnx \
  --split-onnx outputs/final/chipcheck_yolov8_seg_split.onnx \
  --output-dir outputs/final/rknn \
  --calib-dataset outputs/calib_dataset.txt \
  --target-platform rk3576 \
  --name chipcheck_yolov8_seg
```

`convert_rknn.py` prefers `--split-onnx` when it exists. If omitted, it also
checks for `<onnx_stem>_split.onnx` before falling back to the original ONNX.

## Final Artifacts

Expected final directory:

```text
outputs/final/
  chipcheck_yolov8_seg.pt
  chipcheck_yolov8_seg.onnx
  chipcheck_yolov8_seg_split.onnx
  chipcheck_yolov8_seg_fp.rknn
  chipcheck_yolov8_seg_split_int8.rknn
  chip_defect_seg_labels.txt
  calib_dataset.txt
  dataset_report.json
  rknn/rknn_conversion_report.json
```

Split ONNX output names are stable:

```text
boxes
scores
mask_coeffs
protos
```

INT8 RKNN is the deployment target. Keep FP RKNN, original ONNX, and split ONNX
as debug baselines.

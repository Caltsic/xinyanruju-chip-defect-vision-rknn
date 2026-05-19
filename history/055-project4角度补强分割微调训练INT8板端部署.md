# project4角度补强分割微调训练INT8板端部署

Updated: 2026-05-10

## Task

Use the corrected `project_4` segmentation export to supplement weak chip-angle coverage, then complete:

1. cloud upload
2. fine-tune training on RTX 5090
3. ONNX export and split
4. INT8 RKNN conversion
5. pull artifacts back to local
6. cautious board deployment and smoke test

## Inputs

New angle-supplement segmentation export:

```text
chip_seg/cavt_export/project_4_dataset_2026_05_10_10_05_53_coco 1.0.zip
```

Previous full-manual segmentation base:

```text
chip_seg/cavt_export/chipCheck_1_dataset_2026_05_06_08_52_34_coco 1.0.zip
chip_seg/cavt_export/chipCheck_2_dataset_2026_05_06_08_56_04_coco 1.0.zip
chip_seg/cavt_export/chipCheck_4_dataset_2026_05_06_09_01_20_coco 1.0.zip
chip_seg/cavt_export/chipCheck_9_dataset_2026_05_06_09_24_34_coco 1.0.zip
chip_seg/cavt_export/chipCheck_12_dataset_2026_05_06_10_41_37_coco 1.0.zip
chip_seg/cavt_export/task_15_dataset_2026_05_07_12_16_55_coco 1.0.zip
chip_seg/cavt_export/task_16_dataset_2026_05_07_12_17_03_coco 1.0.zip
chip_seg/cavt_export/task_17_dataset_2026_05_07_12_17_09_coco 1.0.zip
chip_seg/cavt_export/task_18_dataset_2026_05_07_12_17_16_coco 1.0.zip
chip_seg/cavt_export/task_19_dataset_2026_05_07_12_17_22_coco 1.0.zip
chip_seg/cavt_export/task_20_dataset_2026_05_07_12_17_29_coco 1.0.zip
chip_seg/cavt_export/task_21_dataset_2026_05_07_12_17_35_coco 1.0.zip
```

Previous best seed weights:

```text
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/chipcheck_yolov8s_seg_full_manual_20260507.pt
```

## Weight Strategy

The new `project_4` set exists to fix previously weak angle coverage, but it is already large enough to affect the distribution by itself.

Final strategy:

- merge `project_4` exactly once into the full-manual segmentation corpus
- do not duplicate or oversample `project_4`
- do not restart from generic `yolov8s-seg.pt`
- fine-tune from the previous best full-manual segmentation weights

Reason:

- keep previous global defect performance
- add angle coverage without biasing too hard toward the new subset
- reduce catastrophic regression risk compared with a from-scratch retrain

## Merged Dataset

Merged output:

```text
cloud_training/yolov8_seg_rknn/dataset_raw/imx678_seg_full_manual_plus_project4_20260510
```

Prepared segmentation dataset summary:

```text
total images kept: 2292
total polygon objects: 7678

train: 1948 images, 6529 polygon objects, 312 empty images
valid: 229 images, 749 polygon objects, 44 empty images
test: 115 images, 400 polygon objects, 16 empty images
```

## Cloud Pipeline

Local upload package:

```text
tmp/seg_angle_finetune_20260510.tar
```

Cloud work directory:

```text
/root/autodl-tmp/chipcheck_seg_angle_finetune_20260510
```

Important pipeline adjustments made during execution:

- reused remote `/root/miniconda3/bin/python` for GPU train/export
- reused remote `/root/miniconda3/envs/rknn232/bin/python` for RKNN conversion
- skipped re-cloning `rknn-toolkit2` after GitHub clone failed
- uploaded missing tools:
  - `tools/split_yolov8_seg_onnx_outputs.py`
  - `tools/diagnose_yolov8_seg_onnx.py`
- pre-uploaded `yolo26n.pt` into the remote training directory to bypass the slow AMP self-check download path
- restored base `ultralytics==8.4.48` after Rockchip fork export attempt dirtied the environment
- updated remote `onnx` / `onnxscript` only as needed for Torch 2.11 ONNX export

## Training Result

Training target name:

```text
chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft
```

Run result:

```text
epochs: 100
early stop: no
best epoch: 95
```

Best segmentation metrics:

```text
precision(M): 0.92444
recall(M):    0.96064
mAP50(M):     0.95801
mAP50-95(M):  0.60205
```

Best box metrics:

```text
precision(B): 0.92604
recall(B):    0.96213
mAP50(B):     0.96010
mAP50-95(B):  0.70345
```

## Export And RKNN

Export result:

```text
exporter = standard_ultralytics_fallback
```

This means Rockchip fork export was not used in the final successful path. Standard Ultralytics export still produced a valid ONNX, and split ONNX plus INT8 RKNN conversion completed successfully.

Final artifacts:

```text
cloud_training/yolov8_seg_outputs_full_manual_plus_project4_20260510_ft/final/chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft.pt
cloud_training/yolov8_seg_outputs_full_manual_plus_project4_20260510_ft/final/chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft.onnx
cloud_training/yolov8_seg_outputs_full_manual_plus_project4_20260510_ft/final/chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft_split.onnx
cloud_training/yolov8_seg_outputs_full_manual_plus_project4_20260510_ft/final/chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft_fp.rknn
cloud_training/yolov8_seg_outputs_full_manual_plus_project4_20260510_ft/final/chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft_split_int8.rknn
cloud_training/yolov8_seg_outputs_full_manual_plus_project4_20260510_ft/final/rknn/rknn_conversion_report.json
cloud_training/yolov8_seg_outputs_full_manual_plus_project4_20260510_ft/train/chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft/results.csv
cloud_training/yolov8_seg_outputs_full_manual_plus_project4_20260510_ft/logs/
```

## Board Deployment

Board model directory:

```text
/userdata/rknn_yolo11_demo/model
```

New model deployed first as a side-path file:

```text
chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft_split_int8.rknn
sha256 = a3de2aaeb71f4bb28d1dba2bf216d83bdf8de33806c495e89c9ec5d37f91c602
```

Previous default model backed up as:

```text
chipcheck_yolov8_seg_split_int8.rknn.bak_pre_project4_20260510
sha256 = 3cea9b18bdf1735e4a6ad25af58684c8e0349c97649121ef8b69ee4dabb97a9c
```

Default board segmentation model then replaced with the new INT8 model:

```text
chipcheck_yolov8_seg_split_int8.rknn
sha256 = a3de2aaeb71f4bb28d1dba2bf216d83bdf8de33806c495e89c9ec5d37f91c602
```

## Smoke Test

Side-path smoke test:

```text
profile: chip-two-stage-obb-seg-imx678
frames processed: 80
exit code: 0
```

Default-path smoke test:

```text
profile: chip-two-stage-obb-seg-imx678
frames processed: 80
exit code: 0
```

Captured snapshots:

```text
tmp/board_smoke_project4_20260510.jpg
tmp/board_smoke_project4_20260510_clean.jpg
tmp/board_smoke_project4_default_20260510.jpg
tmp/board_smoke_project4_default_20260510_clean.jpg
```

Important limitation:

- the recorded smoke-test snapshot shows blank background / wires instead of a chip sample
- therefore this board test verifies runtime compatibility, loading, and non-crash deployment
- it does not yet verify real on-chip scene accuracy for the new model

## Recommended Next Step

Do one real sample verification round on board with chip-in-frame scenes, then compare:

- old 20260507 full-manual segmentation model
- new `project4` fine-tuned segmentation model

Focus on:

- previously weak angles
- mask stability
- false positive rate in clean scenes
- whether the new angle coverage improves manual correction efficiency

# 实时命令默认chip与defect模型版本核对

Updated: 2026-05-11

## Question

Verify which actual chip model and defect model are used by the standard realtime command:

```text
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-obb-seg-imx678 ...
```

## Profile Binding

For profile `chip-two-stage-obb-seg-imx678`, the runtime bindings are:

- `chip_model_kind = obb`
- `defect_model_kind = seg`
- `remote_model = model/chip_roi_yolov8_obb_split_int8.rknn`
- `remote_defect_model = model/chipcheck_yolov8_seg_split_int8.rknn`

Relevant code:

- `tools/adb_imx415_rknn_live_view.py`

## Verified Board Defaults

Board directory:

```text
/userdata/rknn_yolo11_demo/model
```

Verified default chip model:

```text
chip_roi_yolov8_obb_split_int8.rknn
sha256 = 8a12a0abd2dfe7f813701aba0096a7a6643767fd197c90a7eea3b4ffbe502c6b
```

Verified default defect segmentation model:

```text
chipcheck_yolov8_seg_split_int8.rknn
sha256 = a3de2aaeb71f4bb28d1dba2bf216d83bdf8de33806c495e89c9ec5d37f91c602
```

## Actual Model Meanings

The command currently uses:

1. chip model

```text
chip_roi_yolov8_obb_split_int8.rknn
```

This is the OBB chip ROI model from:

```text
cloud_training/chip_roi_yolov8_rknn/outputs_obb_cvat_20260509/final/chip_roi_yolov8_obb_split_int8.rknn
```

2. defect model

```text
chipcheck_yolov8_seg_split_int8.rknn
```

This file name is generic, but its current board content is already the newer:

```text
cloud_training/yolov8_seg_outputs_full_manual_plus_project4_20260510_ft/final/chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft_split_int8.rknn
```

## Important Clarification

The defect model default is ambiguous if judged by file name alone.

- code references the generic board filename `chipcheck_yolov8_seg_split_int8.rknn`
- board content under that filename was replaced on 2026-05-10 with the `project4` fine-tuned segmentation model

So the standard realtime command is **not** using the old 20260505 segmentation content.

## Final Conclusion

Current standard realtime detection uses:

- chip: latest deployed OBB chip ROI model from `20260509`
- defect: latest deployed segmentation model from `20260510 project4 fine-tune`

To avoid future ambiguity, explicit runtime commands can pass both:

```text
--remote-model model/chip_roi_yolov8_obb_split_int8.rknn
--remote-defect-model model/chipcheck_yolov8_seg_split_int8.rknn
```

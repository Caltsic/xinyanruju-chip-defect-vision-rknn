# INT8 split-output 修复与二阶段实时流

更新时间：2026-05-04

## 背景

- 原 `chip_roi_yolov8_detect_int8.rknn` 能加载但无框。
- 板端日志显示原模型是单输出 `(1, 5, 8400)`，`output0` 为 `INT8 zp=-124 scale=2.583458`。
- 该输出把 `xywh` 坐标和 `score` 混在同一张量内量化；坐标范围约 `0..640`，score 范围约 `0..1`，导致 score 量化精度被坐标尺度吞掉。

## 修复方式

- 新增 `tools/split_yolov8_onnx_outputs.py`，把 YOLOv8 detect ONNX 的单输出拆成：
  - `yolov8_boxes`: `(1, 4, 8400)`
  - `yolov8_scores`: `(1, class_count, 8400)`
- 在云端用 RKNN Toolkit2 2.3.2 重转：
  - `chip_roi_yolov8_detect_split_int8.rknn`
  - `chipcheck_yolov8_detect_split_int8.rknn`
- 板端 C++ 后处理新增二输出 YOLOv8 路径，并从模型输出形状推断运行时 `class_count`，支持同一进程内同时加载 1 类 chip 模型和 4 类 defect 模型。

## 产物

本地保留：

```text
cloud_training/chip_roi_outputs_20260504/outputs/final/chip_roi_yolov8_detect_split.onnx
cloud_training/chip_roi_outputs_20260504/outputs/final/rknn_split/chip_roi_yolov8_detect_split_int8.rknn
cloud_training/chip_roi_outputs_20260504/outputs/final/rknn_split/chip_roi_yolov8_detect_split_fp.rknn
cloud_training/autodl_outputs_20260502/outputs/final/chipcheck_yolov8_detect_split.onnx
cloud_training/autodl_outputs_20260502/outputs/final/rknn_split/chipcheck_yolov8_detect_split_int8.rknn
cloud_training/autodl_outputs_20260502/outputs/final/rknn_split/chipcheck_yolov8_detect_split_fp.rknn
```

板端已安装：

```text
/userdata/rknn_yolo11_demo/model/chip_roi_yolov8_detect_split_int8.rknn
/userdata/rknn_yolo11_demo/model/chipcheck_yolov8_detect_split_int8.rknn
/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream
```

## 验证

chip ROI INT8 单模型：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-roi-maixcam --frames 20 --headless --conf 0.25
```

结果：

```text
Processed frames: 20
det=4/4
output num: 2
yolov8_scores scale=0.003786
```

二阶段实时流：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.25
```

结果：

```text
chip model class count=1
defect model class count=4
Processed frames: 12
det=7/7 around 6.9 FPS
```

同配置 `--frames 100 --headless` 稳定性验证通过：

```text
Processed frames: 100
about 7.1-7.3 FPS
```

截图：

```text
captures/chip_roi_split_int8_annotated.jpg
captures/chip_defect_split_int8_annotated.jpg
captures/chip_two_stage_maixcam_int8_conf25_annotated.jpg
```

## 当前结论

- INT8 无框问题已确认不是拍摄画面问题，而是 YOLOv8 单输出 RKNN 量化形态问题。
- split-output INT8 已修通，`chip-roi-maixcam` 默认回到 INT8。
- 二阶段板端单进程 demo 已跑通：全图 chip ROI INT8 -> ROI crop -> defect INT8 -> 坐标映射回全图。
- `defect_conf=0.05` 只适合作诊断，会产生大量大框假阳性；第一版实用 demo 建议 `defect_conf=0.25` 起步。

## 后续注意

- 当前二阶段只选择一个主 chip ROI，选择策略为面积乘置信度优先；多芯片全覆盖后续再做。
- defect 模型在实拍分布上的框仍偏大，下一步应基于 ROI 内实拍数据继续评估阈值、训练集分布和缺陷标签质量。
- MaixCAM MJPG 坏帧仍可能出现 `premature end of data segment`，当前流会跳过坏帧。

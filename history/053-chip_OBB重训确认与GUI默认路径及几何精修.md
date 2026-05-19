# Chip OBB 重训确认与 GUI 默认路径及几何精修

Updated: 2026-05-10

## Summary

本归档记录一次围绕 chip OBB 是否真正重训、GUI 默认 profile 是否误回旧 HBB 路径、板端脚本是否与新版 GUI 同步、以及 GUI 侧 OBB 几何精修的排查和修正。

本文件不记录 SSH、密码、token、云服务器凭据或其他敏感凭据。

## User Question

用户提出质疑：

```text
感觉现在不太对啊，你确定这个chip类框是重新训练过的吗
```

该质疑触发了对历史记录、训练产物、本地 RKNN、板端 RKNN、GUI 默认 profile、板端 helper 脚本、实时短帧输出和当前画面 OBB 几何质量的交叉核实。

## Objective Verification

客观核实结论：chip OBB 确实重训过，并且重训后的 RKNN 已经部署到板端。当前异常不是简单的“没重训”或“没部署”。

证据包括：

- `history/050*` 已记录完整人工 CVAT OBB 标注、训练、RKNN 转换、部署和通道顺序修正过程。
- `outputs_obb_cvat_20260509/final/dataset_report.json` 中统计为：

```text
images=2956
objects=2897
```

- 训练最佳 epoch 为 208，指标为：

```text
mAP50 ~= 0.994970
mAP50-95 ~= 0.987400
```

- 本地重训 RKNN 路径：

```text
cloud_training/chip_roi_yolov8_rknn/outputs_obb_cvat_20260509/final/chip_roi_yolov8_obb_split_int8.rknn
```

- 本地重训 RKNN SHA256：

```text
8a12a0abd2dfe7f813701aba0096a7a6643767fd197c90a7eea3b4ffbe502c6b
```

- 板端 RKNN 路径：

```text
/userdata/rknn_yolo11_demo/model/chip_roi_yolov8_obb_split_int8.rknn
```

- 板端 RKNN SHA256 与本地一致：

```text
8a12a0abd2dfe7f813701aba0096a7a6643767fd197c90a7eea3b4ffbe502c6b
```

- 板端文件大小和时间：

```text
size=10577363
mtime=May 9 19:39
```

因此，本轮排查的判断是：OBB 模型链路确实经历了重训、转换和部署；用户看到的“不太对”需要继续从默认路径、GUI/板端同步和 OBB 角度质量上解释。

## Problems Found

### GUI 默认 profile 仍指向旧 HBB 路径

发现 `tools/chip_capture_gui/settings.py` 中 `CameraSettings.profile` 默认仍是：

```text
chip-two-stage-seg-imx678
```

该 profile 是旧的 HBB/detect chip ROI 路径。也就是说，不传 `--profile` 时，GUI 会看回旧水平框路径，而不是新的 OBB chip ROI 路径。

这会造成一个非常容易误判的现象：即使 OBB 模型已经重训并部署，GUI 默认启动时仍可能显示旧 HBB chip 框，让用户以为当前 chip 类框并未重训或未切换到 OBB。

### 板端 helper 起初不是新版

板端路径：

```text
/userdata/chipcheck_vision/tools/adb_imx415_rknn_live_view.py
```

起初仍是旧 helper，缺少：

```text
CHIP_ROI_OBB_REMOTE_MODEL
```

这会导致新版 GUI 同步到板端后，导入旧 helper 时失败。也就是说，板端 Python helper 与 GUI 代码存在版本不同步风险。

### 短帧实测确认板端确实以 OBB 启动

短帧 headless 实测显示，板端 runtime 已按 OBB chip 模型启动：

```text
chip_model_kind=obb
defect_model_kind=seg
```

返回的 detections 中也包含：

```text
obb_points
```

因此，“当前画面不对”不是因为板端完全没有走 OBB profile。

### 当前 RKNN OBB 角度质量仍有问题

短帧实测中，当前画面模型输出的 OBB angle 约在：

```text
-0.7 到 0.2 度
```

但肉眼观察当前芯片明显倾斜，该角度没有贴合倾斜芯片外轮廓。

该现象说明当前 OBB 模型的角度输出、训练标签学习结果、ONNX/RKNN 转换后的 angle 通道质量，或后处理解释仍存在质量问题。它不是单纯“没部署”问题，也不能只靠确认 SHA256 解决。

## Fixes Made

### GUI 默认改为 OBB 标定 profile

修改文件：

```text
tools/chip_capture_gui/settings.py
```

默认 profile 改为：

```text
OBB_CALIBRATION_PROFILE = chip-two-stage-obb-seg-imx678
```

默认 chip remote model 改为：

```text
model/chip_roi_yolov8_obb_split_int8.rknn
```

默认 defect 路径继续走 segmentation。

OBB 标定默认折中参数为：

```text
chip_conf=0.45
chip_interval=1
roi_smooth_alpha=0.55
roi_hold=1
```

这些参数定位是 GUI 采集/显示折中值：比完全不平滑更稳，比强保持更容易跟随角度变化。

### Qt GUI profile 和 seg toggle 修正

修改文件：

```text
tools/chip_capture_gui/app.py
```

本次修正：

- profile 列表把 OBB profile 放在第一位。
- seg toggle 在 OBB profile 下不再降回旧 HBB profile。
- Qt `_on_frame` 在收到帧后调用：

```text
refine_chip_obbs_in_frame()
```

这样 Qt GUI 显示和后续保存样本前，都会有机会把 chip OBB 从 RKNN 粗框修正为更贴合图像外轮廓的几何框。

### OpenCV GUI 默认路径和精修修正

修改文件：

```text
tools/chip_capture_gui/opencv_app.py
```

本次修正：

- 无 profile 且默认 seg 时，改为 OBB profile。
- 读帧后调用：

```text
refine_chip_obbs_in_frame()
```

OpenCV fallback 因此与 Qt GUI 保持同一默认路径和同一 OBB 几何精修口径。

### 新增 GUI 侧 OBB 几何精修模块

新增文件：

```text
tools/chip_capture_gui/obb_refine.py
```

功能：

- 以 RKNN chip bbox 作为粗定位。
- 在 clean camera image 内做阈值分割。
- 使用 OpenCV `minAreaRect` 提取芯片外轮廓方向。
- 修正 detection 中的：

```text
obb_points
contour
polygon
box
angle
```

该模块用于 GUI 显示和 GUI 保存样本。它不是替代 RKNN OBB 模型，而是在 GUI 端用可见图像几何对 RKNN 粗定位做二次修正。

### Seg sample 保存前也做 OBB 精修

修改文件：

```text
tools/chip_capture_gui/seg_sample.py
```

保存前再次调用 OBB 几何精修，保证保存的：

```text
crop_obb_points
rotated crop
```

更贴近真实芯片外轮廓。

这对后续人工复核、CVAT 精修、角度样本回溯和分割训练样本质量都更重要，因为保存样本如果继续使用近似水平的 RKNN OBB，就会把错误几何固化到数据集中。

### 板端桌面启动脚本指定 OBB profile

修改文件：

```text
board/desktop/chipcheck-qt-gui
board/desktop/chipcheck-hdmi-gui
```

两者都加入：

```text
--profile chip-two-stage-obb-seg-imx678
```

这样从板端桌面入口启动时，不再依赖 Python 默认值，也避免误回旧 HBB profile。

### README 更新

修改文件：

```text
tools/chip_capture_gui/README.md
```

更新内容包括：

- 当前默认走 OBB chip ROI profile。
- GUI 侧存在 OBB 几何精修。
- GUI 侧精修主要影响显示和样本保存。

### 同步到板端

已将以下内容同步到板端：

```text
tools/adb_imx415_rknn_live_view.py
tools/chip_capture_gui/*
tools/chip_capture_gui/obb_refine.py
board/desktop/chipcheck-qt-gui
board/desktop/chipcheck-hdmi-gui
```

同步目标包括：

```text
/userdata/chipcheck_vision
/usr/local/bin
```

并已执行 chmod，确保桌面启动脚本和命令行入口可执行。

## Verification

### py_compile

本地和板端 `py_compile` 均通过。

### CameraSettings 默认值

本地和板端 `CameraSettings()` 均输出：

```text
chip-two-stage-obb-seg-imx678 model/chip_roi_yolov8_obb_split_int8.rknn 0.45 1 0.55 1
```

这确认默认 profile、默认 OBB RKNN 路径和折中参数已经在本地与板端一致。

### 短帧 headless

短帧 headless 验证结果：

```text
Processed frames: 12
```

日志确认：

```text
chip_model_kind=obb
defect_model_kind=seg
```

这说明板端短帧链路确实按 OBB chip + seg defect 启动。

### OBB 精修效果

未精修前，当前帧模型 OBB angle 约为：

```text
-0.694 deg
```

精修后示例变为约：

```text
-13.57 deg
```

快照：

```text
tmp/verify_gui_refined_obb.jpg
```

显示旋转框已经贴合芯片外轮廓。该验证支持本次 GUI 侧几何精修确实解决了“显示和保存样本的 OBB 几何口径不贴合当前图像”的问题。

## Residual Risk And Follow-Up

本次修正解决的是 GUI/采集显示和保存样本的几何口径问题。

板端 C++ defect crop 仍使用 RKNN OBB 模型输出的原始 OBB。如果要让板端两阶段推理本身也按精修角度裁剪，则需要后续继续做以下工作之一：

- 将同类几何精修逻辑移植到 C++ 板端实时链路。
- 或重新检查 OBB 训练标签、ONNX 导出、RKNN 转换、angle 通道解释和后处理质量，修正模型原生角度输出。

当前判断：

- OBB 重训和部署已经确认。
- GUI 默认误回旧 HBB profile 的风险已经修正。
- GUI 与板端 helper 不同步导致导入失败的风险已经修正。
- GUI 显示和保存样本已增加几何精修。
- 板端 C++ 两阶段推理的 defect crop 仍未使用 GUI 侧精修角度，这是后续如果追求板端生产推理角度一致性时必须处理的残留项。

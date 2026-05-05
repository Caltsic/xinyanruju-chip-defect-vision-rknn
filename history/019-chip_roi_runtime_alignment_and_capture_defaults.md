# chip ROI 运行接入与拍摄默认参数

更新日期：2026-05-04

## 结论

- 可以把 `chip` 类作为第一阶段识别目标：先在全图上定位整颗芯片，再用该 ROI 辅助调整芯片位置，并为后续缺陷/字符/引脚模型提供稳定裁剪输入。
- 当前推荐默认拍摄/预览参数：
  - `Light 50%`
  - `Brightness -6`
  - `Contrast 1.28`
  - `Gamma 0.91`
  - `Saturation 0.30`
  - `Sharpness 0.85`
  - `Denoise 6`
- 这组参数的方向合理：低饱和度压住 WS2812 偏色，轻微负亮度和 1.28 对比度增强芯片表面纹理，0.85 锐化提高边缘/字符可见性。后续仍应以模型稳定输出为准，而不是只看人眼观感。

## 已改动

- `tools/chip_capture_gui/settings.py`
  - 将上述拍摄参数设为 GUI 默认值。
  - 补光默认亮度改为 `0.50`，上限保留 `0.80`。
- `tools/chip_capture_gui/image_adjust.py`
  - 将实时预览降噪从 `fastNlMeansDenoisingColored` 换成轻量双边滤波，避免 1280x720 预览时调 `Denoise` 卡死。
- `tools/chip_capture_gui/app.py`
  - 滑条初始值和 Reset 均读取 `ImageAdjustSettings()` 默认值。
  - `Denoise` 滑条关闭 tracking，松手后再触发更新。
- `tools/roi_defect_closed_loop.py`
  - 默认优先加载 `cloud_training/chip_roi_outputs_20260504/outputs/final/chip_roi_yolov8_detect.onnx`。
  - `chip-yolov8` 无框时回退旧的暗区域/边缘 ROI。
  - 输出图增加芯片中心到画面中心的偏移和大小比例提示。
- `tools/adb_imx415_rknn_live_view.py`
  - 新增 `chip-roi`、`chip-roi-maixcam` profile。
  - `chip-*` profile 启动时默认先下发 WS2812：`rgb=190,255,100`、`brightness=0.50`。
  - PC 端实时窗口和 annotated snapshot 默认套用 `Brightness -6 / Contrast 1.28 / Gamma 0.91 / Saturation 0.30 / Sharpness 0.85 / Denoise 6`。
- `rknn_work/board_yolo11_src/examples/yolo11/cpp/CMakeLists.txt`
  - 新增 `rknn_chip_roi_camera_stream`、`rknn_chip_roi_maixcam_stream` 构建目标，按 `OBJ_CLASS_NUM=1` 编译。
- `rknn_work/board_yolo11_src/examples/yolo11/model/chip_roi_labels.txt`
  - 新增单类标签文件：`chip`。

## 命令

PC 侧单帧闭环，优先用 chip ONNX 找 ROI：

```powershell
F:\anaconda\python.exe .\tools\roi_defect_closed_loop.py --capture-maixcam --save-dir .\captures\roi_defect_closed_loop_capture
```

板端 chip-only 实时框，当前 profile 默认加载已验证出框的 `chip_roi_yolov8_detect_fp.rknn`：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-roi-maixcam --conf 0.25
```

## 注意

- 当前新增的是 chip-only 实时入口和 PC 侧两阶段验证；真正“一路实时显示 chip 框 + ROI 内缺陷框”的板端二阶段融合还需要继续改 C++，让一个进程内串联两个 RKNN 模型。
- `Denoise 6` 已可作为默认预览参数，但不要重新换回 NLM 实时逐帧降噪；它会拖死 GUI。
- `chip_roi_yolov8_detect_int8.rknn` 已部署到板端且能加载为 `1x5x8400`，但当前 MaixCAM 帧上 `conf=0.25/0.05` 均无框；FP RKNN 在同画面 `conf=0.25` 可出 `det=1/1`。后续需单独修 INT8 量化/反量化或重新转换。
- 实时脚本里的图像参数是 PC 端预览/截图参数，不改变板端 NPU 输入；要影响推理输入需迁入 C++ 预处理。

# chip_capture_gui 二阶段实时调参

更新时间：2026-05-05

## 背景

二阶段实时检测当前效果可用，但引脚清晰度仍需现场快速优化。目标是在 `F:\anaconda\python.exe -m tools.chip_capture_gui` 内同时保留拍照标注，并加入等价于命令行二阶段实时检测的画面：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3
```

## 已实现

- `CameraSettings` 默认改为 `chip-two-stage-maixcam`：
  - `remote_binary=./rknn_chip_two_stage_maixcam_stream`
  - `remote_model=model/chip_roi_yolov8_detect_split_int8.rknn`
  - `conf=0.25`
  - `chip_conf=0.25`
  - `defect_conf=0.35`
  - `display_max_defects=3`
- GUI 新增 `Mode` 区：
  - `Live Detect`：显示 chip + defect 检测框。
  - `Capture / Label`：关闭检测框，保留采集标注流程。
  - `Draw detection boxes`：可随时单独开关检测框。
  - `Save adjusted capture`：默认开启，采集保存当前高级参数处理后的画面。
- `Capture ROI` 现在优先使用板端二阶段输出中的 `chip` 框作为初始 ROI；没有 chip 框时再回退暗区域/边缘 ROI。
- 高级选项仍复用已有预览处理链：
  - Brightness
  - Contrast
  - Gamma
  - Saturation
  - Sharpness
  - Denoise
  - CLAHE
- 新增快速预设：
  - `Pins`：提高边缘清晰度，便于观察引脚问题。
  - `Text`：提高对比度并启用 CLAHE，便于观察丝印。
  - `Damage`：保守参数，便于观察破损/划痕。
  - `Reset`：回到当前项目默认值。
- 每次采集仍写入 `images/`、`labels/`、`meta/`、`previews/` 和 `manifest.csv`；元数据中新增 `capture_adjusted` 并保留完整 `image_adjust` 参数。

## 重要边界

当前高级选项只影响 GUI 预览和采集落盘图像，不会直接改变板端 NPU 输入。这样做是为了先快速比较不同画面风格对人工观察和标注的帮助。后续如果确认某组轻量预处理稳定提升引脚/丝印/破损识别，再迁入板端 C++ 推理前处理。

## 验证

Python 语法检查通过：

```powershell
F:\anaconda\python.exe -m py_compile .\tools\chip_capture_gui\app.py .\tools\chip_capture_gui\camera.py .\tools\chip_capture_gui\settings.py .\tools\chip_capture_gui\storage.py
```

远端命令构造确认会启动二阶段程序：

```text
./rknn_chip_two_stage_maixcam_stream --model model/chip_roi_yolov8_detect_split_int8.rknn --device /dev/video73 --width 1280 --height 720 --fps 30 --skip 3 --frames 0 --conf 0.25 --nms 0.45 --format mjpg --two-stage --defect-model model/chipcheck_yolov8_detect_split_int8.rknn --chip-conf 0.25 --defect-conf 0.35
```

使用 GUI 相机类短帧读取验证通过：

```text
preflight {'camera': True, 'stream': True, 'spidev': True}
frame=0 size=1280x720 det=1 fps=0.0 focus=69
frame=7 size=1280x720 det=2 fps=9.6 focus=69
```

## 使用入口

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui
```

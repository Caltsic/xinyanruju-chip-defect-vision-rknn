# 板端 NPU 输入与实时显示画面一致

日期：2026-05-05

## 目标

用户希望实时识别准确率能直接反映当前画面参数是否适合引脚、丝印、破损等类别。因此 MaixCAM 链路改为：

```text
MaixCAM MJPG/YUYV
  -> 板端解码 RGB888
  -> 板端应用同一套图像调整参数
  -> 调整后的 RGB888 给 chip ROI / defect NPU
  -> 调整后的画面回传 PC 显示
```

## 当前实现

- 板端 `live_camera_yolo.cc` 新增 input-adjust 参数：
  - `--input-adjust`
  - `--no-input-adjust`
  - `--input-brightness`
  - `--input-contrast`
  - `--input-gamma`
  - `--input-saturation`
  - `--input-sharpness`
  - `--input-adjust-file`
- 默认配置文件：

```text
/tmp/chip_input_adjust.conf
```

- `tools/adb_imx415_rknn_live_view.py` 在 `chip-two-stage-maixcam` profile 下默认开启 input-adjust，并在开流前把当前参数写入板端配置文件。
- `tools/chip_capture_gui` 新增 `Sync view to NPU input`，默认开启；GUI 的 Brightness/Contrast/Gamma/Saturation/Sharpness 会同步给板端。

## 算法边界

- `Brightness/Contrast/Gamma` 合成 256 项 LUT。
- `Saturation` 使用 RGB luma-blend，避免 HSV 转换成本。
- `Sharpness` 使用轻量 luma unsharp，可通过 `--input-sharpness 0` 关闭。
- `Denoise` 和 `CLAHE` 不进入板端 NPU 输入，只保留为 GUI 观察或落盘辅助。
- 当前优先覆盖 MaixCAM MJPG/YUYV 解码后的 RGB888 路径，不强行改 IMX415/NV12 路径。

## 默认参数

```text
Light 50%
Brightness -6
Contrast 1.28
Gamma 0.91
Saturation 0.30
Sharpness 0.85
Denoise 6 仅用于 GUI 观察/落盘，不进 NPU 输入
```

## 验证命令

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 160 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3 --save-snapshot .\captures\chip_two_stage_input_adjust_fast_annotated.jpg --save-clean-snapshot .\captures\chip_two_stage_input_adjust_fast_clean.jpg --remote-log /tmp/chip_two_stage_input_adjust_fast.log
```

验证结果：

```text
Processed frames: 160
input_adjust=on brightness=-6 contrast=1.280 gamma=0.910 saturation=0.300 sharpness=0.850 adjust_file=/tmp/chip_input_adjust.conf
```

输出截图：

```text
captures/chip_two_stage_input_adjust_fast_annotated.jpg
captures/chip_two_stage_input_adjust_fast_clean.jpg
```

## 性能结论

- 当前默认 input-adjust 约 `8.3-9.2 FPS`。
- 未做全帧输入调整时的二阶段节奏优化基线约 `10.3-10.9 FPS`。
- 性能损耗主要来自 1280x720 全帧 RGB 预处理和锐化；若现场优先速度，第一步应降低或关闭 `Sharpness`：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3 --input-sharpness 0
```

## 常用入口

GUI：

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui
```

实时命令：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3
```

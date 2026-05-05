# chip_capture_gui 双后端与板端 OpenCV 界面

更新时间：2026-05-05

## 背景

7 寸 HDMI LCD 已在泰山派 3M 上通过 `1280x720 + RGB + force_dvi` 正常显示。为了现场不依赖 Windows 预览窗口，需要让芯片检测画面直接显示在板端 HDMI 屏上，同时继续保留 Windows 端 PyQt `chip_capture_gui` 的采集标注工作流。

## 实现

- `tools/chip_capture_gui/settings.py`
  - `CameraSettings` 新增 `backend`，默认 `adb`，不改变 PC 端现有行为。
- `tools/chip_capture_gui/camera.py`
  - 新增 `RknnCamera` 协议、`create_camera()`。
  - `AdbRknnCamera` 继续通过 ADB `exec-out` 读取 RYL1 流。
  - 新增 `LocalRknnCamera`，在板端直接执行 `rknn_chip_two_stage_maixcam_stream` 并读取 stdout。
  - 新增 `write_input_adjust_config()`，支持 ADB 写入和本地写入 `/tmp/chip_input_adjust.conf`。
- `tools/chip_capture_gui/ws2812.py`
  - 新增 `LocalWs2812Controller` 和 `create_ws2812_controller()`。
  - 板端本地模式直接调用 `/userdata/rknn_yolo11_demo/ws2812_spi.py`。
- `tools/chip_capture_gui/opencv_app.py`
  - 新增 OpenCV 简化界面，复用现有二阶段检测框绘制、chip ROI 初框算法和 `CaptureStorage` 输出结构。
  - 支持实时检测框、Pins/Text/Damage/Reset 预设、参数微调、补光亮度、Capture ROI、ROI 复核、Accept/Negative。
- `tools/chip_capture_gui/__main__.py`
  - `--opencv` 显式进入 OpenCV 界面。
  - 若环境缺少 PyQt5，会自动 fallback 到 OpenCV 界面。

## 启动命令

Windows PyQt 主入口：

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui
```

Windows OpenCV + ADB 后端：

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui --opencv --backend adb
```

板端 HDMI OpenCV + 本地后端：

```bash
cd /userdata/chipcheck_vision
python3 -m tools.chip_capture_gui --opencv --backend local --fullscreen
```

板端桌面快捷方式已安装；当前为非全屏 `960x540` 左上角窗口，避免 7 寸屏在 720p HDMI 模式下裁切全屏画面：

```text
/usr/local/bin/chipcheck-hdmi-gui
/home/lckfb/Desktop/chipcheck-hdmi.desktop
/usr/share/applications/chipcheck-hdmi.desktop
```

仓库内对应模板：

```text
board/desktop/chipcheck-hdmi-gui
board/desktop/chipcheck-hdmi.desktop
board/desktop/99-chipcheck-spidev.rules
```

## OpenCV 快捷键

```text
Tab       选择 Brightness / Contrast / Gamma / Saturation / Sharpness / Light
+/-       实时模式微调选中项；复核模式缩放 ROI
1/2/3/0   Pins / Text / Damage / Reset
C         抓图并进入 ROI 复核
O         开关检测框
I         开关板端 input-adjust 同步
A/D/W/S   复核模式移动 ROI
Enter     接受 ROI
Delete/N  标为负样本
Q/Esc     退出
```

## 验证

- Windows 本地：
  - `F:\anaconda\python.exe -m py_compile ...` 通过。
  - `F:\anaconda\python.exe -m tools.chip_capture_gui --opencv --help` 通过。
- 板端：
  - 已同步到 `/userdata/chipcheck_vision/tools`。
  - `python3 -m py_compile tools/chip_capture_gui/...` 通过。
  - 本地后端 3 帧烟测通过：

```text
preflight {'camera': True, 'stream': True, 'spidev': True}
frame 0 1280 720 detections 0 fps 0.0 focus 103
frame 1 1280 720 detections 0 fps 14.7 focus 105
frame 2 1280 720 detections 0 fps 13.6 focus 102
```

- OpenCV HDMI 窗口用 `timeout` 短跑可启动，退出后无 `chip_capture_gui` 或 `rknn_chip_two_stage_maixcam_stream` 残留进程。
- 已用 `gio launch /home/lckfb/Desktop/chipcheck-hdmi.desktop` 模拟桌面点击，确认可拉起 `python3 -m tools.chip_capture_gui --opencv --backend local` 和二阶段流进程。
- 用户反馈全屏模式只能看到局部画面且找不到关闭入口后，已把 `/usr/local/bin/chipcheck-hdmi-gui` 改为：

```bash
python3 -m tools.chip_capture_gui --opencv --backend local --screen-width 960 --screen-height 540 --window-x 0 --window-y 0
```

- `opencv_app.py` 新增 `--window-x/--window-y` 参数，非全屏模式会 `moveWindow()` 到指定位置。
- 已在板端为 OpenCV QT 补充字体链接，避免启动时反复打印 `QFontDatabase` 字体目录警告：

```text
/srv/rk3576-storage/miniforge/lib/python3.13/site-packages/cv2/qt/fonts/DejaVuSans.ttf
```

## 注意

- OpenCV 简化界面不依赖 PyQt5，适合板端 HDMI 屏现场观察和快速采集。
- 现阶段仍是单 chip ROI bbox 复核，不支持多芯片多框全量标注。
- 板端 local 后端和 PC ADB 后端都会占用 `/dev/video73`，不要与其它实时窗口同时运行。
- 桌面快捷方式日志写入 `/tmp/chipcheck-hdmi-gui.log`；若点击后无画面，先查看该日志。

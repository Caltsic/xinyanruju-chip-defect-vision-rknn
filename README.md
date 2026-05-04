# 泰山派3M-RK3576开发项目说明

## 项目定位

本项目面向嘉立创立创·泰山派3M-RK3576开发板进行全面开发。当前主线是基于 IMX415 摄像头模组开展视觉识别开发，围绕摄像头接入、图像采集、视觉算法验证、板端部署与系统集成逐步推进。

## 当前基础状态

- 已为泰山派开发板完成基础系统配置。
- 已配置好 Hermes，后续可作为辅助开发、板端操作与自动化协作工具使用。
- 本地已保存官方开发资料，作为优先参考来源。
- 已安装面向嵌入式 Linux、内核模块、交叉编译、Windows 连板调试、OpenCV 视觉、高级视觉算法和推理优化的用户级辅助 Skills。

## 资料入口

- 本地资料目录：`F:\WORKSPACE\泰山派\立创·泰山派3开发板资料`
- 官方资料网址记录：`F:\WORKSPACE\泰山派\泰山派资料网址.txt`
- 当前官方资料网址：<https://wiki.lckfb.com/zh-hans/tspi-3-rk3576/download-center.html>

## 开发主线

当前阶段以 IMX415 摄像头模组视觉识别开发为主线，优先关注：

- 泰山派3M-RK3576硬件、系统镜像、SDK与内核驱动资料梳理。
- IMX415摄像头模组接入、驱动、设备树、采集链路与调试流程。
- 基于板端环境的图像采集、预处理、模型推理与识别结果验证。
- Hermes 辅助下的开发、调试、运行验证与资料沉淀。

## 已安装辅助 Skills

用户级 Skills 安装位置：`C:\Users\Kaltsit\.agents\skills`

- `embedded-systems`
- `linux-kernel-modules`
- `cross-gcc`
- `embedded-iot`
- `wsl-embedded-debugging`
- `computer-vision-opencv`
- `senior-computer-vision`
- `ml-inference-optimization`

## 长期维护约定

- 本文件作为项目基础说明，后续项目方向、环境状态、关键路径变化时应同步更新。
- 涉及硬件、系统、内核、SDK、AI应用和模块移植的问题，优先查阅本地资料目录，再查阅官方资料网站。
- 对关键结论尽量记录来源路径或官方页面，避免后续重复查证。
- 与泰山派板端交互、环境检查、自动化执行相关的工作，应优先考虑是否可以借助 Hermes 提高效率。

## IMX415 实时预览与识别

当前已验证 IMX415 在板端通过 `/dev/video42` 输出 ISP 处理后的 `NV12` 画面，可用 ADB 拉流到电脑端预览或运行 YOLO ONNX 物品识别。

纯实时预览：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_yolo_preview.py --no-detect
```

YOLO 物品识别预览，会自动优先查找本地 `YOLO11\yolo11n.onnx`，找不到或加载失败时退化为纯预览：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_yolo_preview.py
```

无窗口冒烟测试并保存截图：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_yolo_preview.py --no-detect --headless --frames 1 --save-snapshot .\captures\preview_smoke.jpg
```

窗口中按 `q` 或 `Esc` 退出。当前默认 ADB 设备号为 `23f3c08e840ba991`，默认采集尺寸为 `960x540`，并丢弃开流后的前 8 帧以避开 3A 启动收敛闪烁。

调焦和稳定度辅助预览：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_yolo_preview.py --no-detect --diagnostics
```

`focus` 数值越大通常表示越清晰；物理旋转镜头时观察该数值，尽量让它达到局部最大并保持稳定。

## RK3576 NPU 实时 YOLO 识别预览

当前已部署板端 RKNN YOLO11 实时流程序：

```text
/userdata/rknn_yolo11_demo/rknn_yolo11_camera_stream
```

当前芯片缺陷检测已部署板端实时流程序：

```text
/userdata/rknn_yolo11_demo/rknn_chip_defect_camera_stream
```

电脑端芯片缺陷实时显示命令：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py
```

该命令默认使用 `chip-defect` profile，板端加载：

- `model/chipcheck_yolov8_detect_int8.rknn`
- `model/chip_defect_labels.txt`

电脑端 YOLO11/COCO 实时显示仍可显式指定：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile yolo11
```

该链路在板端从 `/dev/video42` 采集 IMX415 的 `NV12` 画面，调用 RK3576 NPU 跑 RKNN 检测模型，通过 ADB `exec-out` 把帧和检测框传回电脑，由 Windows 端 OpenCV 实时显示并画框。

无窗口冒烟测试：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --frames 3 --headless --save-snapshot .\captures\rknn_live_smoke.jpg
```

保存不带状态栏/检测框的干净相机帧，用于排查紫屏、颜色和模型输入分布：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --frames 20 --headless `
  --save-snapshot .\captures\diag_annotated.jpg `
  --save-clean-snapshot .\captures\diag_clean.jpg
```

窗口中按 `q` 或 `Esc` 退出。默认参数为 `960x540 @ 8fps`、ADB 设备号 `23f3c08e840ba991`。

状态栏中的 `focus` 是电脑端按拉普拉斯方差计算的清晰度评分。当前 IMX415 链路没有暴露 V4L2 focus/VCM 控制，若画面发糊，需要旋转镜头手动调焦，并观察 `focus` 数值调到局部最大。

可调参数：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --conf 0.20 --nms 0.45
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --remote-model model/chipcheck_yolov8_detect_fp.rknn
```

`--remote-model model/chipcheck_yolov8_detect_fp.rknn` 用于 FP 基线对比；正常实时部署优先使用默认 INT8 模型。

对保存图片做电脑端 ONNX 离线诊断：

```powershell
F:\anaconda\python.exe .\tools\diagnose_chip_defect_onnx.py
```

状态栏中的 `det raw/drawn` 表示板端返回框数/电脑端实际绘制框数；`0/0` 表示板端模型后处理没有返回候选框。

## Astra Pro Plus RGB 芯片检测

当前已验证 Astra Pro Plus 的 RGB UVC 路径可用：

```text
/dev/video73  USB 2.0 Camera RGB
/dev/video74  UVC metadata
```

深度传感器 `2bc5:060f ORBBEC Depth Sensor` 已枚举，但 Debian 自带 OpenNI2 无法直接打开，当前芯片缺陷检测暂不使用深度。

板端已新增：

```text
/userdata/rknn_yolo11_demo/rknn_chip_defect_demo
/userdata/rknn_yolo11_demo/rknn_chip_defect_astra_stream
```

Astra 实时芯片检测冒烟：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py `
  --remote-binary ./rknn_chip_defect_astra_stream `
  --device /dev/video73 --width 640 --height 480 --fps 30 --skip 3 `
  --frames 5 --headless `
  --save-snapshot .\captures\astra_chip_live_annotated.jpg `
  --save-clean-snapshot .\captures\astra_chip_live_clean.jpg
```

低阈值观察弱候选：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py `
  --remote-binary ./rknn_chip_defect_astra_stream `
  --device /dev/video73 --width 640 --height 480 --fps 30 --skip 3 `
  --conf 0.05
```

当前冒烟结果能稳定收到 Astra 帧并完成 NPU 推理，但在当前桌面远景/遮挡画面上为 `det 0/0`。需要把真实芯片缺陷样本放到 Astra 清晰成像距离内再判断模型效果。

## MaixCAM Pro UVC 芯片检测

MaixCAM Pro 需要在本机屏幕打开 `UVC Camera` 应用，并显示类似：

```text
UVC started. Please use 'Guvcview'
and mjpeg channel.
```

泰山派端当前验证到的节点：

```text
/dev/video73  maixcam: UVC Camera
/dev/video74  metadata/companion node
```

注意：MaixCAM 默认 UVC feeder 可能输出 `/bin/cat_224.jpg` 静态测试图；只有打开官方 `UVC Camera` 应用后，`MJPG 1280x720` 才是实时相机画面。不要单独执行 `/etc/init.d/uvc_tool.sh stop_server`，这会让 MaixCAM 的 USB gadget 掉线。

板端已新增：

```text
/userdata/rknn_yolo11_demo/rknn_chip_defect_maixcam_stream
```

MaixCAM 实时芯片检测冒烟：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py `
  --profile chip-defect-maixcam `
  --frames 5 --headless --conf 0.05 `
  --save-snapshot .\captures\maixcam_chip_live_annotated.jpg `
  --save-clean-snapshot .\captures\maixcam_chip_live_clean.jpg
```

持续实时显示：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-defect-maixcam --conf 0.05
```

该 profile 默认使用 `/dev/video73`、`1280x720`、`MJPG`、`30fps`，板端解码 MJPEG 后给 RKNN 推理，并把 NV12 帧回传给电脑端显示。当前测试能稳定收到 MaixCAM 实时帧并完成 NPU 推理；在当前远景小芯片画面上 `conf=0.05` 和 `conf=0.001` 均为 `det 0/0`。

MaixCAM 的 MJPEG UVC 流偶发坏包，日志可能出现 `premature end of data segment`、`does not contain JPEG SOI marker` 等信息。`rknn_chip_defect_maixcam_stream` 已做坏帧跳过和 JPEG 起始标记重同步；若连续坏包过多才退出。

### 开发注意事项速查

硬件和视觉链路的易错点已整理到：

```text
history/014-硬件视觉链路开发注意事项.md
```

后续遇到补光偏紫、MaixCAM UVC 模式、MJPG 坏帧、`Device or resource busy`、ROI/预处理、GUI 线程关闭等问题，优先阅读该文件。

### MaixCAM ROI + 预处理最小闭环

当前芯片在 `1280x720` 全幅中占比偏小，直接全图检测容易 `det=0/0`。新增 PC 端验证工具先自动找芯片 ROI，再对 ROI 运行 `raw + light_gamma_clahe` 两路 ONNX 缺陷检测，并把框映射回原图：

```powershell
F:\anaconda\python.exe .\tools\roi_defect_closed_loop.py --capture-maixcam --save-dir .\captures\roi_defect_closed_loop_capture
```

也可以对已保存的清洁帧运行：

```powershell
F:\anaconda\python.exe .\tools\roi_defect_closed_loop.py .\captures\maixcam_broken_current_clean.jpg --save-dir .\captures\roi_defect_closed_loop_final
```

输出文件示例：

```text
captures/roi_defect_closed_loop_capture/maixcam_current_clean_roi_closed_loop.jpg
captures/roi_defect_closed_loop_capture/maixcam_current_clean_variants.jpg
```

该工具是板端化前的最小验证闭环；后续可把 ROI/preprocess 逻辑迁入 `rknn_chip_defect_maixcam_stream`，或训练一个独立 `chip` 定位模型。

## Git 配置

当前开发分支：

```text
chipCheck
```

远端仓库：

```text
git@github.com:Caltsic/-IMX415_Vision.git
```

本仓库建议使用的本地 Git 身份：

```powershell
git config --local user.name "Caltsic"
git config --local user.email "2769003879@qq.com"
```

Windows 本机使用的 GitHub SSH key：

```powershell
git config --local core.sshCommand "ssh -i C:/Users/Kaltsit/.ssh/id_ed25519_github -F /dev/null"
```

不要把私钥文件提交进仓库；这里只记录本机路径和推荐配置。

## WS2812-8 环形补光

当前已启用 40Pin 的 SPI1 M1 spidev：

```text
/dev/spidev1.0
```

WS2812-8 推荐接线：

```text
WS2812 VCC / 5V  -> 泰山派 40Pin 物理 2 或 4 脚 5V
WS2812 GND       -> 泰山派 40Pin 物理 20 脚 GND
WS2812 DI / DIN  -> 泰山派 40Pin 物理 19 脚 SPI1_MOSI(M1)
WS2812 DO / DOUT -> 不接；只有继续串接下一组灯珠时才接下一组 DI
```

低亮度白光：

```powershell
F:\anaconda\python.exe .\tools\adb_ws2812_ring.py set --rgb 255,255,255 --brightness 0.08 --count 8
```

关灯：

```powershell
F:\anaconda\python.exe .\tools\adb_ws2812_ring.py off
```

8 颗 WS2812 全白满亮约 480mA，不建议直接满亮从板子 5V 长时间取电。先用 `0.05-0.20` 亮度调试；若高亮使用，建议外接 5V 供电并与泰山派共地。

## 芯片缺陷 YOLOv8 RKNN 云训练包

当前已新增云端训练包源码：

```text
cloud_training/yolov8_rknn
```

目标是训练半导体芯片缺陷 4 类检测框模型，并同时产出：

- `chipcheck_yolov8_detect.pt`
- `chipcheck_yolov8_detect.onnx`
- `chipcheck_yolov8_detect_fp.rknn`
- `chipcheck_yolov8_detect_int8.rknn`
- `chip_defect_labels.txt`
- `calib_dataset.txt`

上传云算力使用的压缩包由以下脚本生成：

```powershell
F:\anaconda\python.exe .\tools\build_chip_defect_cloud_package.py
```

云端包会把原始中文路径数据集重映射到 ASCII 路径：

```text
dataset_raw/chip_defect_raw
```

第一版只做 YOLOv8 detect，不做 segmentation。数据准备脚本会把原始数据集中混合存在的 polygon 标注转换成 bbox 标注，并输出独立的检测训练数据副本，不覆盖原始标签。

当前板端已新增 `rknn_chip_defect_camera_stream`，用于 YOLOv8 单输出 `1x8x8400` 缺陷检测后处理；旧 `rknn_yolo11_camera_stream` 仍保留给 YOLO11/COCO 80 类验证使用。

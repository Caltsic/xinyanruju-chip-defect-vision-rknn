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

- `model/chipcheck_yolov8_detect_split_int8.rknn`
- `model/chip_defect_labels.txt`

已新增一类 `chip` ROI 实时 profile。当前默认使用已修通的 split-output INT8：

- `model/chip_roi_yolov8_detect_split_int8.rknn`
- `model/chip_roi_labels.txt`

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-roi-maixcam --conf 0.25
```

二阶段实时融合入口会在一个板端进程内串联 `chip ROI INT8 -> ROI crop -> defect INT8`：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

当前 defect 框会比 chip 框更容易跳动；脚本已默认对二阶段 profile 开启显示端短时平滑，并在板端对 chip ROI crop 做轻度平滑。当前实拍阈值扫描后建议用较高缺陷阈值和较高显示上限，避免靠 top-k 截断：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

二阶段默认不是每帧都重跑 chip/defect 两个模型，而是 `chip-interval=3`、`defect-interval=2`。未启用板端全帧输入调整时，该节奏在当前 UVC 1280x720 MJPG 流上约 `10.3-10.9 FPS`；当前默认启用 input-adjust 后的速度见下文。速度优先、芯片基本静止时可以用：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20 --chip-interval 5 --defect-interval 3
```

该模式实测约 `11.3-12.4 FPS`，代价是 chip/defect 检测结果更新频率更低。

`--defect-conf 0.05` 可用于低阈值诊断，但当前实拍画面会产生较多大框假阳性；`--no-smooth-boxes --no-display-filter` 可用于查看原始逐帧输出。

启动 `chip-*` 实时 profile 时，脚本会默认先设置 WS2812：

```text
rgb=190,255,100
brightness=0.50
```

二阶段 UVC profile 现在默认把当前推荐画面参数下沉到板端 NPU 输入。UVC MJPG/YUYV 解码为 `RGB888` 后，板端先应用同一套轻量调整，再把调整后的 RGB888 同时送给 chip ROI / defect NPU，并转换为 NV12 回传给 PC 显示：

```text
Brightness -6
Contrast 1.28
Gamma 0.91
Saturation 0.30
Sharpness 0.85
```

`Denoise 6` 仍保留为 GUI 人工观察/落盘参数，不进入板端 NPU 输入；`CLAHE` 也不进入 NPU 输入。`--save-clean-snapshot` 在该模式下保存的是板端回传的已同步调整 clean 帧，不再是未调整原始帧。若现场优先速度，可降低或关闭锐化：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20 --input-sharpness 0
```

当前默认输入调整实测约 `8.3-9.2 FPS`；未做全帧输入调整时的二阶段节奏优化基线约 `10.3-10.9 FPS`。

## IMX678 USB UVC 芯片检测

当前新 IMX678 模组通过 USB 接入后被系统识别为 UVC 设备：

```text
lsusb: 1bcf:2cd1 Sunplus Innovation Technology Inc. DECXIN CAMERA
/dev/video73  DECXIN CAMERA: DECXIN CAMERA
/dev/video74  UVC metadata，不用于取图
```

该设备支持 `MJPG` 与 `YUYV`，推荐继续使用 `MJPG 1280x720` 作为实时检测输入；`1920x1080`/`3840x2160` 虽可枚举，但会增加 USB 解码和板端预处理负载。

当前正式 profile：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

验证截图：

```text
captures/imx678_profile_two_stage_annotated.jpg
captures/imx678_profile_two_stage_clean.jpg
```

当前烟测可出 `chip` 与 `broken` 框，但画面明显虚焦，`focus` 约 `3`，后续需要优先调整镜头/工作距或 UVC focus 控制。

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

该工具现在会优先加载本地训练好的 `chip_roi_yolov8_detect.onnx` 来定位整颗芯片；若模型文件不存在或没有检出 chip 框，才回退到旧的暗区域/边缘 ROI。输出图中黄色框是缺陷模型输入 ROI，绿色/黄色中心线用于辅助判断芯片是否居中、大小是否合适。

该工具是板端化前的最小验证闭环；后续可把“chip ROI -> ROI 内缺陷检测”的两阶段逻辑迁入板端 RKNN/C++，或先用新增的 `chip-roi-maixcam` profile 单独实时显示整颗芯片框。

### GUI 实时调参与标注

当前推荐用一体化 GUI 做二阶段实时观察、画面调参和 chip ROI 采集标注：

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui
```

Windows 端也可用 OpenCV 简化界面，后端仍走 ADB：

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui --opencv --backend adb
```

泰山派 HDMI 屏可直接用板端本地后端显示，不经过 ADB 拉流：

```bash
cd /userdata/chipcheck_vision
python3 -m tools.chip_capture_gui --opencv --backend local --fullscreen
```

板端桌面已安装快捷方式 `Chip Check HDMI / 芯片检测 HDMI`，双击即可执行同一入口。桌面快捷方式默认使用 `960x540` 左上角窗口，避免 7 寸屏在 720p HDMI 模式下裁切全屏画面。若点击后无画面，先查看板端日志：

```bash
tail -80 /tmp/chipcheck-hdmi-gui.log
```

GUI 默认启动等价于当前二阶段实时命令的板端流：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

界面中的 `Live Detect` 用于实时观察 chip + defect 框，`Capture / Label` 用于关闭检测框专注标注，`Draw detection boxes` 可随时单独开关检测框。`Sync view to NPU input` 默认开启，GUI 会把 `Brightness/Contrast/Gamma/Saturation/Sharpness` 同步写到板端 `/tmp/chip_input_adjust.conf`，因此实时画面与 NPU 输入一致。`Denoise/CLAHE` 不进入 NPU 输入，只作为人工观察或落盘辅助。

`Save adjusted capture` 默认开启，采集时会把当前可见画面保存为标注样本，并在 `meta/*.json` 记录具体参数。

OpenCV 简化界面快捷键：`Tab` 选择 Brightness/Contrast/Gamma/Saturation/Sharpness/Light，`+/-` 微调；`1/2/3/0` 为 Pins/Text/Damage/Reset 预设；`C` 抓图进入 ROI 复核；复核时 `A/D/W/S` 移框、`+/-` 缩放、`Enter` 接受、`Delete` 或 `N` 标负样本、`Q/Esc` 退出。

### chip 类定位数据集

整颗芯片 `chip` 类定位相关文件放在根部浅层目录：

```text
chip_roi/
```

该目录目前保存规划和标注规则：

```text
chip_roi/README.md
chip_roi/dataset_plan.md
chip_roi/label_rules.md
```

后续伪标签、实拍采集和人工复核输出分别放入 `chip_roi/generated/`、`chip_roi/captures/`、`chip_roi/review/`，这些目录默认不入 git。`chip` 框只负责稳定裁出芯片 ROI，不追求缺陷级轮廓精度。

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

## 芯片缺陷 YOLOv8-Seg RKNN 云训练包

当前已新增独立分割训练包：

```text
cloud_training/yolov8_seg_rknn
```

该包用于复用原始 polygon 标注训练四类缺陷分割模型，不会改动现有 detect 训练包。数据准备脚本会保留 YOLO segmentation 行：

```text
class_id x1 y1 x2 y2 x3 y3 ...
```

bbox-only 行默认跳过并写入 `dataset_report.json`。完整云端流程会产出：

- `chipcheck_yolov8_seg.pt`
- `chipcheck_yolov8_seg.onnx`
- `chipcheck_yolov8_seg_split.onnx`
- `chipcheck_yolov8_seg_fp.rknn`
- `chipcheck_yolov8_seg_split_int8.rknn`
- `chip_defect_seg_labels.txt`
- `calib_dataset.txt`

首版分割部署仍沿用二阶段路径：`chip ROI INT8 -> ROI crop -> defect seg INT8`。PC/GUI 侧已兼容 contour 回传并用半透明掩膜绘制；板端 seg hook 可识别 `boxes/scores/mask_coeffs/protos` split 输出和标准 `pred + protos` 输出，使用 mask coeff 与 proto 生成轻量 contour，mask 点过少时回退 bbox contour。

2026-05-05 已完成第一轮上板烟测：`rknn_chip_two_stage_maixcam_stream` 已原生重编译并替换到 `/userdata/rknn_yolo11_demo/`，旧二进制备份为 `rknn_chip_two_stage_maixcam_stream.bak_pre_seg_20260505`；`chipcheck_yolov8_seg_split_int8.rknn` 已部署到 `/userdata/rknn_yolo11_demo/model/`。IMX678 UVC 10 帧 headless 测试通过，状态栏 `FPS 8.7 | focus 159 | 1280x720 | det 2/2 | frame 9`，截图中 `scratch 0.56` 已显示分割轮廓/掩膜。

云端训练入口：

```bash
cd cloud_training/yolov8_seg_rknn
python scripts/run_all.py --raw-dataset dataset_raw/chip_defect_raw --work-dir outputs --model yolov8n-seg.pt --imgsz 640 --epochs 150 --device 0 --overwrite-dataset
```

板端模型部署到 `/userdata/rknn_yolo11_demo/model/chipcheck_yolov8_seg_split_int8.rknn` 后，PC 侧 seg profile：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

分割首轮观察可降低缺陷阈值并关闭确认延迟，便于直接看 contour 是否稳定：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.30 --defect-confirm 1 --display-max-defects 20
```

## 二阶段 chip ROI + defect 实时检测

当前默认实时路径优先使用 INT8：

```text
chip ROI INT8 -> chip ROI crop -> defect INT8 -> RYL1 实时回传
```

常规启动命令：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

该 profile 会自动设置 WS2812 补光，并默认启用板端 input-adjust，使 NPU 输入与回传显示画面一致。板端已经加入 defect 时序滤波：默认 `--defect-confirm 3` 要求连续命中后输出，`--defect-hold 3` 在短时 miss 后保持，`--defect-match-iou 0.10` 和 `--defect-match-center 0.55` 用于同类/跨类稳定匹配。`--display-max-defects 0` 表示保留显示 NMS 但不做数量截断。

更稳但反应稍慢：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --defect-hold 5 --defect-smooth-alpha 0.25 --display-max-defects 20
```

如果需要排查板端原始滤波输出，关闭 PC 端显示平滑和显示过滤：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --no-smooth-boxes --no-display-filter
```

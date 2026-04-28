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

窗口中按 `q` 或 `Esc` 退出。默认 ADB 设备号为 `2e2609c37dc21c0a`，默认采集尺寸为 `960x540`，并丢弃开流后的前 8 帧以避开 3A 启动收敛闪烁。

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

电脑端实时显示命令：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py
```

该链路在板端从 `/dev/video42` 采集 IMX415 的 `NV12` 画面，调用 RK3576 NPU 跑 `YOLO11n RKNN`，通过 ADB `exec-out` 把帧和检测框传回电脑，由 Windows 端 OpenCV 实时显示并画框。

无窗口冒烟测试：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --frames 3 --headless --save-snapshot .\captures\rknn_live_smoke.jpg
```

窗口中按 `q` 或 `Esc` 退出。默认参数为 `960x540 @ 8fps`、ADB 设备号 `2e2609c37dc21c0a`。

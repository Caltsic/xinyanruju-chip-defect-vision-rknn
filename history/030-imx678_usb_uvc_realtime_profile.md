# IMX678 USB UVC 实时检测接入

更新时间：2026-05-05

## 识别结果

用户新接入的 IMX678 是 USB UVC 形态，不是当前系统里的 MIPI CSI/ISP 设备。板端识别信息：

```text
lsusb: 1bcf:2cd1 Sunplus Innovation Technology Inc. DECXIN CAMERA
dmesg: Found UVC 1.00 device DECXIN CAMERA (1bcf:2cd1)
```

V4L2 节点：

```text
/dev/video73  DECXIN CAMERA: DECXIN CAMERA  视频流
/dev/video74  UVC Payload Header Metadata   元数据，不用于取图
```

`/dev/video73` 支持：

```text
MJPG:
  3840x2160 @ 30
  2592x1944 @ 30
  2048x1536 @ 30
  1920x1080 @ 60
  1280x960  @ 60
  1280x720  @ 60
  1024x768  @ 60
  800x600   @ 60
  640x480   @ 60
YUYV:
  高分辨率帧率较低，1280x720 最高 10 FPS，640x480 最高 30 FPS
```

## 工程接入

- 当前板端 C++ 流程序已经支持 UVC 单平面 `MJPG/YUYV`，因此 IMX678 可以复用原 MaixCAM UVC 二阶段流二进制。
- PC 端新增正式 profile：
  - `chip-defect-imx678`
  - `chip-roi-imx678`
  - `chip-two-stage-imx678`
- `tools/chip_capture_gui/settings.py` 默认 profile 已切到 `chip-two-stage-imx678`。
- 板端 `/userdata/chipcheck_vision` 已同步更新 `tools/adb_imx415_rknn_live_view.py`、`tools/chip_capture_gui/settings.py` 和 `tools/chip_capture_gui/app.py`。

## 当前推荐命令

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

## 验证

烟测命令：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-imx678 --frames 20 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20 --save-snapshot .\captures\imx678_profile_two_stage_annotated.jpg --save-clean-snapshot .\captures\imx678_profile_two_stage_clean.jpg --remote-log /tmp/imx678_profile_two_stage.log
```

结果：

```text
camera /dev/video73 configured: 1280x720 MJPG, fps=30, buffers=4, planes=1
Processed frames: 20
frame=18 fps=8.1 focus=3 size=1280x720 det=2/2
```

截图：

```text
captures/imx678_profile_two_stage_annotated.jpg
captures/imx678_profile_two_stage_clean.jpg
```

当前画面里模型输出：

```text
chip 0.63
broken 0.74
```

## 注意

- 画面明显虚焦，`focus` 约 `3`，远低于之前可用清晰画面的水平；后续应优先调镜头、工作距离或 UVC focus 控制。
- IMX678 当前是 UVC 路径，和 MaixCAM 一样绕过 RK ISP；不要按 MIPI/CSI IMX415 的 `/dev/video42` 逻辑排查。
- 虽然设备枚举到高分辨率 MJPG，实时检测默认仍建议先用 `1280x720`，否则 MJPG 解码、全帧 input-adjust 和二阶段 NPU 调度都会增加负载。

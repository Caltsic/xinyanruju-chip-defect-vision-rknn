# Astra Pro Plus 芯片检测执行日志

## 2026-05-03

- 完成 Astra 最小硬件验证。
- `lsusb` 看到 RGB UVC 和 Depth Sensor 两个 USB 设备。
- `v4l2-ctl --list-devices` 看到 `USB 2.0 Camera`，节点为 `/dev/video73` 和 `/dev/video74`。
- 使用 `/dev/video73` 抓取 `1280x720 MJPG` 单帧成功，并拉回 `captures/astra_rgb_1280x720.jpg`。
- 使用 `/dev/video73` 抓取 `1920x1080 MJPG` 单帧成功，并拉回 `captures/astra_rgb_1080p.jpg`。
- 连续 `1280x720 MJPG` 30 帧采集成功，约 `24 fps`。
- 尝试 GStreamer `openni2src` 打开深度失败，错误为 `no devices found`。
- 创建 Astra 开发计划文件，下一步开始新增独立 Astra RGB 检测二进制。
- 新增 `rknn_chip_defect_demo` CMake 目标，按 `OBJ_CLASS_NUM=4` 和 `chip_defect_labels.txt` 编译。
- 板端编译并安装 `rknn_chip_defect_demo` 成功。
- 使用 Astra 抓取 `/tmp/astra_chip.jpg`，运行：

```bash
cd /userdata/rknn_yolo11_demo
export LD_LIBRARY_PATH=$PWD/lib:$LD_LIBRARY_PATH
./rknn_chip_defect_demo model/chipcheck_yolov8_detect_int8.rknn /tmp/astra_chip.jpg
```

- 单图 NPU 推理成功，RGA letterbox 和 `rknn_run` 正常，无检测框输出；结果图拉回 `captures/astra_chip_try_int8_out.png`。
- 扩展 `live_camera_yolo.cc`，支持 UVC 单平面 `YUYV` 采集并转换为 `RGB888` 推理、`NV12` 回传。
- 新增 `rknn_chip_defect_astra_stream` CMake 目标，默认 `/dev/video73`、`640x480`、`30fps`。
- 板端编译并安装 `rknn_chip_defect_astra_stream` 成功。
- 实时冒烟成功：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py `
  --remote-binary ./rknn_chip_defect_astra_stream `
  --device /dev/video73 --width 640 --height 480 --fps 30 --skip 3 `
  --frames 5 --headless `
  --save-snapshot .\captures\astra_chip_live_annotated.jpg `
  --save-clean-snapshot .\captures\astra_chip_live_clean.jpg
```

- 输出 `Processed frames: 5`，状态栏显示 `det 0/0`。
- 低阈值 `--conf 0.05` 再测一次仍为 `det 0/0`，说明当前画面没有模型可识别的芯片缺陷目标。

## 2026-05-03 MaixCAM Pro UVC 尝试

- 泰山派端最初可通过 USB 看到 `359f:2120 sipeed maixcam`，但只枚举出 RNDIS/NCM 网络接口，没有 UVC Video Class，也没有新增 `/dev/videoX`。
- 通过 MaixCAM USB 网络 `10.97.103.1` 登录成功，默认账号密码为 `root/root`。
- MaixCAM 内部存在 `maix.uvc`、`/etc/init.d/uvc_tool.sh` 和 `/maixapp/apps/uvc_camera/uvc_camera`，但默认 `/boot/usb.uvc` 不存在。
- 写入 `/boot/usb.uvc`：

```text
mjpg 640x480
mjpg 1280x720
yuyv 640x480
```

- 尝试后台执行 `/etc/init.d/S08usbdev stop; sleep 2; /etc/init.d/S08usbdev start` 重新绑定 USB gadget 后，泰山派端 MaixCAM USB 设备断开且未重新枚举。
- 重置泰山派下游 USB hub 后仍未恢复 MaixCAM 枚举；当前需要物理复位/断电重插 MaixCAM Pro 后继续验证。
- 物理复位后 MaixCAM 重新枚举成功，并出现 UVC：
  - `/dev/video73`: `maixcam: UVC Camera`
  - `/dev/video74`: 配套节点
  - `lsusb -t` 显示 `Class=Video, Driver=uvcvideo`
- `/dev/video73` 支持：
  - `YUYV 640x480`
  - `MJPG 640x480`
  - `MJPG 1280x720`
- 抓取 `/dev/video73` 成功，但 `640x480` 和 `1280x720` 输出均为同一张 `224x224 JPEG` 默认静态测试图，保存为：
  - `captures/maixcam_uvc_640.jpg`
  - `captures/maixcam_uvc_720.jpg`
- 通过 USB 网络 SSH 到 MaixCAM 后确认默认进程为：

```text
/etc/init.d/uvc-gadget-server.elf -u /dev/video0 -d -i /bin/cat_224.jpg
```

- 尝试执行 `/etc/init.d/uvc_tool.sh stop_server` 切换到真实相机 feeder 时，MaixCAM USB gadget 再次掉线，泰山派端只剩 USB hub。下一次应避免单独调用 `stop_server`，优先在 MaixCAM 屏幕启动官方 UVC Camera 应用，或物理复位后直接启动 `/maixapp/apps/uvc_camera/uvc_camera` 观察其是否自动接管 feeder。
- 用户在 MaixCAM 屏幕打开官方 `UVC Camera` 应用后，`MJPG 1280x720` 抓图恢复为真实相机画面，保存为：
  - `captures/maixcam_uvc_app_640.jpg`
  - `captures/maixcam_uvc_app_720.jpg`
- 验证 `YUYV 640x480` 通道为全黑帧，因此 MaixCAM 必须走 `MJPG` 通道。
- 扩展 `live_camera_yolo.cc`，新增单平面 UVC `MJPG` 解码路径：
  - 使用 libjpeg-turbo 解码 MJPEG 为 `RGB888` 供 RKNN 推理
  - 同步转换为 `NV12`，保持现有 `RYL1` PC 显示协议不变
  - 新增 `--format yuyv|mjpg` 参数
- 新增并安装 `rknn_chip_defect_maixcam_stream`，默认 `/dev/video73`、`1280x720`、`MJPG`、`30fps`、`skip=3`。
- 扩展 `tools/adb_imx415_rknn_live_view.py`，新增 `chip-defect-maixcam` profile。
- MaixCAM 实时 NPU 冒烟跑通：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py `
  --profile chip-defect-maixcam `
  --frames 5 --headless --conf 0.05 `
  --save-snapshot .\captures\maixcam_chip_live_annotated.jpg `
  --save-clean-snapshot .\captures\maixcam_chip_live_clean.jpg
```

- 输出 `Processed frames: 5`，状态栏显示 `size=1280x720 det=0/0`，保存：
  - `captures/maixcam_chip_live_clean.jpg`
  - `captures/maixcam_chip_live_annotated.jpg`
- 低阈值 `--conf 0.001` 再测仍为 `det 0/0`，保存：
  - `captures/maixcam_chip_live_conf001_clean.jpg`
  - `captures/maixcam_chip_live_conf001_annotated.jpg`
- 用户反馈实时窗口启动后在 `Processed frames: 3/36/107` 处自动关闭。检查 `/tmp/rknn_yolo11_camera_stream.log`，原因是 MaixCAM MJPEG 流偶发非 JPEG/损坏 buffer，例如：

```text
MJPG header decode failed: Not a JPEG file: starts with 0x1a 0x61
```

- 修复 `rknn_chip_defect_maixcam_stream`：
  - 在 MJPEG buffer 内搜索 JPEG `FFD8` SOI 标记并重同步
  - 单个坏 MJPEG 帧不再导致进程退出，而是 requeue buffer 后继续
  - 连续 60 个坏 MJPEG 帧才退出
- 板端重新编译并安装后，执行 300 帧稳定性测试：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py `
  --profile chip-defect-maixcam `
  --frames 300 --headless --conf 0.05 `
  --remote-log /tmp/rknn_maixcam_stability.log
```

- 测试通过，输出 `Processed frames: 300`，实际显示速率约 `9-10 fps`；日志仍可见少量坏 MJPEG 包，但已被跳过。

## 2026-05-04 MaixCAM ROI + 轻量预处理最小闭环

- 确认当前模型只包含 4 个缺陷类：`ZF-scratch`、`scratch`、`broken`、`pinbreak`，不包含整颗 `chip` 类。
- 对当前破损芯片全图验证：板端 INT8 RKNN 在 `conf=0.05`、`0.001`、`0.0001` 均无框；本地 ONNX 在可见破损区域的 `broken` 响应约 `0.00010`。
- 对同一实拍图裁出芯片 ROI 后验证：
  - `raw` ROI 可得到 `broken≈0.35`。
  - `light_gamma_clahe` 有助于增强部分候选，但也会增加 `ZF-scratch`/`pinbreak` 候选。
- 新增工具：

```text
tools/roi_defect_closed_loop.py
```

- 工具流程：

```text
全图 -> 自动 chip ROI -> ROI 裁剪 -> raw + light_gamma_clahe -> ONNX 缺陷检测 -> 框映射回原图
```

- 使用上一张实拍清洁帧验证：

```powershell
F:\anaconda\python.exe .\tools\roi_defect_closed_loop.py .\captures\maixcam_broken_current_clean.jpg --save-dir .\captures\roi_defect_closed_loop_final
```

- 输出摘要：

```text
raw: det@0.050=2 [broken:0.359, pinbreak:0.064, ...]
light_gamma_clahe: det@0.050=4 [broken:0.191, ZF-scratch:0.126, pinbreak:0.114, ...]
merged@0.050=4 [broken:0.359/raw, ZF-scratch:0.126/light_gamma_clahe, pinbreak:0.114/light_gamma_clahe, ZF-scratch:0.081/light_gamma_clahe]
```

- 保存结果：
  - `captures/roi_defect_closed_loop_final/maixcam_broken_current_clean_roi_closed_loop.jpg`
  - `captures/roi_defect_closed_loop_final/maixcam_broken_current_clean_variants.jpg`

- `--capture-maixcam` 当前抓帧闭环验证成功：

```powershell
F:\anaconda\python.exe .\tools\roi_defect_closed_loop.py --capture-maixcam --save-dir .\captures\roi_defect_closed_loop_capture
```

- 输出摘要：

```text
pinbreak:0.388/raw, scratch:0.181/raw, pinbreak:0.105/light_gamma_clahe, ...
```

- 保存结果：
  - `captures/roi_defect_closed_loop_capture/maixcam_current_clean_roi_closed_loop.jpg`
  - `captures/roi_defect_closed_loop_capture/maixcam_current_clean_variants.jpg`

## 2026-05-04 硬件视觉链路注意事项落档

- 新增后续开发速查文件：

```text
history/014-硬件视觉链路开发注意事项.md
```

- 覆盖主题：
  - WS2812 补光接线、SPI overlay、避免偏紫的 RGB 配比：`--rgb 190,255,100 --brightness 0.5`。
  - MaixCAM 必须打开官方 `UVC Camera` 应用，使用 `MJPG 1280x720`；`YUYV 640x480` 实测全黑。
  - MaixCAM MJPEG 流偶发坏包，实时程序必须跳过坏帧和搜索 JPEG SOI。
  - `/dev/video73` 不能并发打开，`Device or resource busy` 优先查 GUI/实时窗口/抓帧脚本是否同时运行。
  - 当前缺陷模型没有 `chip` 类，推荐先做 ROI 再检测。
  - 预处理默认 `raw + light_gamma_clahe`，强白平衡会导致类别漂移。
  - bbox 框偏大是模型/标签属性，精细定位需要轮廓、mask 或分割模型。

- 已更新：
  - `history/000-history-index-and-rules.md`
  - `README.md`
  - `findings.md`

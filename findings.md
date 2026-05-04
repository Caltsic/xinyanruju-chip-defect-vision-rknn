# Astra Pro Plus 开发发现

## 已确认硬件状态

- ADB 设备：`2e2609c37dc21c0a`
- Astra RGB UVC：`2bc5:050f Orbbec ... USB 2.0 Camera`
- Astra 深度：`2bc5:060f Orbbec ... ORBBEC Depth Sensor`
- RGB 视频节点：`/dev/video73`
- UVC metadata 节点：`/dev/video74`
- RGB 驱动：`uvcvideo`

## RGB 能力

`/dev/video73` 支持：

- `MJPG`: `2048x1536@30`、`1920x1080@30`、`1280x720@30`、`640x480@30`、`320x240@30`
- `YUYV`: `1920x1080@3`、`2048x1536@3`、`1280x960@10`、`1280x720@10`、`640x480@30`、`320x240@30`

已成功抓图：

- `captures/astra_rgb_1280x720.jpg`
- `captures/astra_rgb_1080p.jpg`

连续 `1280x720 MJPG` 采集 30 帧成功，实测约 `24 fps`。

## 深度状态

板端已有 Debian OpenNI2 基础库和 GStreamer `openni2src`，但打开 Astra 深度失败：

```text
DeviceOpen using default: no devices found
```

判断：当前缺少 Astra Pro Plus 所需的奥比私有 OpenNI/Orbbec 驱动；深度不作为当前芯片缺陷 demo 的输入。

## 对模型兼容性的判断

当前 RKNN 芯片缺陷模型不绑定 IMX415，只要求最终输入为模型需要的 `640x640 RGB/NHWC` 图像。Astra 可兼容跑 demo，关键改动在采集和颜色转换层，不在模型和后处理层。

## 已实现代码路径

- `rknn_chip_defect_demo`：单图芯片缺陷 NPU demo，按 4 类芯片缺陷标签编译。
- `rknn_chip_defect_astra_stream`：Astra RGB 实时流 demo，默认 `/dev/video73`、`640x480`、`YUYV`、`30fps`。
- `live_camera_yolo.cc` 已支持两类输入：
  - IMX415/RKISP：`Video Capture Multiplanar` + `NV12`
  - Astra/UVC：`Video Capture` + `YUYV`
- Astra 路径会把 YUYV 转为：
  - `RGB888` 给 RKNN 推理
  - `NV12` 给现有 RYL1 协议和 PC 端显示脚本

## 当前检测结果

- Astra 1080p JPEG 单图 NPU 推理跑通，输出 `captures/astra_chip_try_int8_out.png`。
- Astra 实时 NPU 流跑通，输出：
  - `captures/astra_chip_live_clean.jpg`
  - `captures/astra_chip_live_annotated.jpg`
  - `captures/astra_chip_live_conf005_clean.jpg`
  - `captures/astra_chip_live_conf005_annotated.jpg`
- `conf=0.25` 和 `conf=0.05` 均为 `det 0/0`。当前画面不是芯片缺陷近景，且有遮挡/远景/模糊，不能用它判断模型失效。

## MaixCAM Pro UVC 状态

- 直接连接到泰山派 USB 后，MaixCAM Pro 默认不是普通 UVC 摄像头，而是 USB Device 复合网络设备：
  - RNDIS Communications Control
  - RNDIS Ethernet Data
  - CDC Network Control Model
  - CDC Network Data
- 泰山派端可通过 NCM 获得 `10.97.103.100/24`，MaixCAM 侧为 `10.97.103.1`，SSH 端口开放，默认 `root/root` 可登录。
- MaixCAM 固件使用 `/boot/usb.*` 文件控制 USB gadget。`/boot/usb.uvc` 存在时，`/etc/init.d/S08usbdev` 会调用 `/etc/init.d/uvc_tool.sh mount /boot/usb.uvc` 并启动 `uvc-gadget-server.elf`。
- 本次热重启 USB gadget 后设备未重新枚举，说明 MaixCAM 作为 UVC 摄像头还不能按 Astra 的方式直接接入现有实时检测链路。下一步应先物理复位恢复 USB 网络，再优先关闭 `/boot/usb.uvc` 恢复 NCM，之后用 MaixCAM 屏幕的 USB Settings 或官方 UVC app 方式验证。
- 复位后 UVC 节点可以出现，但默认 feeder 是 `/bin/cat_224.jpg` 静态测试图，因此仅看到 `/dev/video73` 不等于已经得到真实相机画面。
- 风险点：单独执行 `/etc/init.d/uvc_tool.sh stop_server` 会让 USB gadget 掉线且不自动恢复。切换真实相机流时应使用官方 UVC Camera app 的完整启动流程，而不是只杀默认 feeder。
- 官方 `UVC Camera` 应用启动后，`MJPG 1280x720` 是真实相机画面；`YUYV 640x480` 虽然枚举存在，但实测为全黑帧。
- MaixCAM 接入当前 RKNN 检测链路的正确路径是 `MJPG -> RGB888 -> RKNN`，并把同一帧转换成 `NV12` 回传给 PC 端显示。当前已由 `rknn_chip_defect_maixcam_stream` 实现。
- 当前画面中芯片只占 `1280x720` 画面很小一部分，且清晰度偏低；`conf=0.05` 和 `conf=0.001` 均无检测，不能说明 RKNN 模型在 MaixCAM 上不兼容，只说明当前成像/目标尺度不匹配训练分布。
- MaixCAM 的 MJPEG UVC 流不是每个 buffer 都是完整 JPEG，偶发损坏包会导致 libjpeg-turbo 报 `premature end of data segment` 或找不到 JPEG SOI。实时链路必须容忍并跳过坏帧，不能把单帧解码失败当作摄像头流终止。

## MaixCAM ROI 与预处理发现

- 当前缺陷模型类别只有 `ZF-scratch`、`scratch`、`broken`、`pinbreak`，没有 `chip` 类；全画面检测不会框整颗芯片。
- 当前破损芯片全图直接送模型时，ONNX 在可见破损 ROI 的 `broken` 响应约 `0.00010`；板端 INT8 RKNN 即使降到 `conf=0.0001` 也无框。
- 同一张实拍图裁出芯片 ROI 后，ONNX 可给出可用响应，证明当前画面不是完全不可识别，而是尺度/ROI 问题优先。
- 训练集中 `broken` 标注框中位面积约占图像 `8.6%`，当前可见缺角约占全图 `0.49%`，尺度差约 17 倍；当前整颗芯片也只约占全图 `2.0%`。
- 轻量预处理有帮助但必须受控：
  - `raw` ROI 对当前缺角给出 `broken≈0.35`。
  - `light_gamma_clahe` 可增强部分引脚/划痕响应，但也会提高 `ZF-scratch` 等候选。
  - 强白平衡会把当前缺角倾向推成 `ZF-scratch`，不适合作为默认唯一输入。
- 现有训练图像可以通过背景/暗区域分割生成 `chip` 伪标签，足以启动一个 `chip` 定位模型，但伪标签仍需要抽检修正。
- 新增 PC 端最小闭环工具 `tools/roi_defect_closed_loop.py`，默认执行：自动 ROI、`raw + light_gamma_clahe` 两路 ONNX、合并 NMS、映射回原图。

## 后续开发注意事项落档

- 已新增 `history/014-硬件视觉链路开发注意事项.md` 作为后续开发速查入口。
- 该文件集中记录：
  - WS2812 补光接线、SPI overlay、避免偏紫的 RGB 配比。
  - MaixCAM UVC 必须打开官方 `UVC Camera` app，且使用 MJPG 通道。
  - MJPEG 偶发坏包必须跳过，不能把单帧解码失败当成流结束。
  - `/dev/video73` 只能单路占用，多个实时/抓帧进程并行会导致 `Device or resource busy`。
  - 当前缺陷模型无 `chip` 类，全图检测应先做 ROI。
  - 默认预处理使用 `raw + light_gamma_clahe`，避免强白平衡导致类别漂移。
  - 精细定位需要 mask/轮廓/分割，bbox 模型本身不会输出精确缺陷轮廓。

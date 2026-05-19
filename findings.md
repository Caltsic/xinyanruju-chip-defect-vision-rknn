# Astra Pro Plus 开发发现

## MiniMind-O CPU-only 语音助手发现

- MiniMind-O 上游项目说明 `minimind-3o` 主干约 `0.1B`，2026-05-05 发布权重为 `115M`；但完整 Omni 链路还依赖 SenseVoice-Small、SigLIP2、Mimi、CAMPPlus 等组件。
- 官方快速开始参考 Python `3.10`；当前板端主 Python 为 `/srv/rk3576-storage/miniforge/bin/python3`，版本 `3.13.12`。完整依赖不应直接安装到现有环境。
- 板端已存在 ALSA 音频设备和工具：
  - `/dev/snd/*`
  - `card0 rockchip-es8388`
  - `card1 rockchip-hdmi`
  - `card2 rockchip-dp0`
  - `/usr/bin/arecord`
  - `/usr/bin/aplay`
- 当前工程策略：先部署 CPU-only、按键式、非自启语音助手骨架，完整 MiniMind-O 模型接入作为后续独立阶段。
- 当前已部署的是非侵入式语音助手骨架，不是完整 MiniMind-O 实模型：
  - 已完成 GUI 按键/快捷键、录音、占位推理、HDMI 播放和检测并发验证。
  - 尚未安装 MiniMind-O 的 PyTorch/FunASR/Mimi/SenseVoice 依赖，也未下载模型权重。
  - 后续接入实模型应通过 `--voice-command` 调用独立 Python 3.10 环境中的脚本，避免污染现有 Python 3.13 检测 GUI 环境。
- 非干扰验证中，OBB+Seg 检测 `100` 帧并发语音占位链路仍保持约 `6.3-6.7 FPS`，说明音频采集/播放和占位命令本身不抢 NPU、不打断摄像头检测。
- `/srv/rk3576-storage/yolov8_env` 已在 2026-05-12 改名隔离为 `/srv/rk3576-storage/yolov8_env.disabled_20260512`。当前检测 GUI 和语音助手均走 `miniforge`，隔离后验证正常。旧快捷命令 `/usr/local/bin/ycuda`、`/usr/local/bin/condaactivate` 仍引用原路径，后续若确认不再需要旧 YOLO/ONNX Python 实验环境，可以删除 disabled 目录释放约 `5.3G`。

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

- IMX678 新模组当前是 USB UVC 形态，板端识别为 `DECXIN CAMERA (1bcf:2cd1)`，视频节点 `/dev/video73`，metadata 节点 `/dev/video74`。
- IMX678 UVC 支持 `MJPG 1280x720 @ 60`、`1920x1080 @ 60`、`3840x2160 @ 30`；实时检测默认仍先用 `1280x720` 控制解码和预处理成本。
- `chip-two-stage-imx678` 已跑通二阶段 INT8 烟测，截图为 `captures/imx678_profile_two_stage_annotated.jpg`；当前画面可出 `chip 0.63` 和 `broken 0.74`，但 `focus` 约 `3`，明显虚焦。
- `chip_capture_gui` 已支持双后端：Windows 默认 `adb`，板端可用 `local` 后端直接启动 `/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream` 并读取同一套 RYL1 stdout 协议。
- 板端 HDMI 现场入口为 OpenCV 简化界面：

```bash
cd /userdata/chipcheck_vision
python3 -m tools.chip_capture_gui --opencv --backend local --fullscreen
```

- OpenCV 界面不依赖 PyQt5，适合当前板端环境；快捷键覆盖实时框显示、Pins/Text/Damage/Reset、参数微调、补光亮度、Capture ROI、ROI 复核和 Accept/Negative。
- 板端本地后端烟测结果：`/dev/video73`、二阶段 stream binary、`/dev/spidev1.0` 均存在，3 帧 `1280x720` 读取成功；短跑 OpenCV 窗口后无残留进程。
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

## chip 类定位数据集目录决策

- 新增根部浅层目录 `chip_roi/`，专门承载整颗芯片 `chip` 类定位相关文档、规则和后续小型配置。
- 不把 `chip` 类文件混入现有中文训练集深目录，避免路径过深、来源混乱和后续生成文件污染原始数据。
- `chip_roi/generated/`、`chip_roi/captures/`、`chip_roi/review/` 用于后续伪标签、硬件采集、人工复核输出，已加入 `.gitignore`。
- `chip` 框用于 ROI 裁剪，不追求像素级贴边；推荐覆盖芯片主体、可见引脚和约 `5-15%` 背景余量。
- 第一版样本量建议：现有训练集伪标签 `1000-2000` 张，人工复核 `100-200` 张，硬件实拍正样本 `300-600` 张，负样本 `100-200` 张。

## chip 类半自动伪标签执行发现

- 新增 `tools/build_chip_roi_dataset.py`：现有训练集走暗区域/边缘分割，实拍图走当前 ROI 风格的方形扩展框。
- 新增 `tools/review_chip_roi_labels.py`：OpenCV 轻量复核 GUI，按键只保留 A/D/W/S 微调、`+/-` 扩缩、`Enter` 接受、`Delete` 标负样本。
- 现有训练集已生成 `2406` 条候选，预览接触表显示多数能覆盖芯片主体和引脚区域，适合作为第一版伪标签再抽检。
- 实拍全目录不能无筛选直接当正样本，因为包含 annotated、crop、ONNX 诊断、远景和无芯片图；第一批仅筛选 MaixCAM 清洁帧生成 `8` 条候选。
- 多芯片场景暂未自动补框；第一版按用户要求保留为少量手工补充，不把多目标全覆盖作为当前阻塞。

## chip_capture_gui 一体化采集标注

- `tools.chip_capture_gui` 已改成一体化采集/标注入口，默认输出 `chip_roi/generated/gui_capture/`。
- GUI 现在自动按 prefix 生成顺序文件名，如 `chip_0001.jpg`，不需要手动改名。
- 每次 `Capture ROI` 会保存 `images/`、`labels/`、`meta/`、`previews/` 和 `manifest.csv`，并用当前 ROI 算法生成初始 `chip` 框。
- GUI 支持按钮和键盘两种调框方式：`A/D/W/S` 移动，`+/-` 扩缩，`Accept/Enter` 接受，`Negative/Delete` 写空标签。
- 第一版仍只支持单个正框 bbox；多芯片场景后续少量手动补框，不作为当前 GUI 阻塞项。

## chip ROI 云端训练发现

- 第一版 chip ROI 数据已足够启动轻量定位模型训练：复核伪标签 `754` 个正样本、`46` 个负样本；GUI 实拍有效纳入 `375` 个正样本、`3` 个负样本。
- GUI manifest 中存在图片缺失记录时，训练包构建脚本会跳过并写入 warning；本次跳过 `chip_0288.jpg`、`chip_0313.jpg`。
- 打包后的 YOLO 数据集为 `1178` 张图、`1129` 个 chip 框、`49` 张空标签负样本。负样本原图分组不足，当前全部放入 train，后续需要补真实无芯片负样本进入 valid/test 才能严肃评估误检。
- 云端训练依赖顺序应保持为：训练依赖 -> 训练/ONNX 导出 -> RKNN-Toolkit2 -> FP/INT8 RKNN 转换。不要在训练前先装 RKNN-Toolkit2，以免其依赖集合影响 PyTorch 2.8 + CUDA 12.8。
- INT8 量化校准集使用训练集抽样 `300` 张图，输出 `calib_dataset.txt`；板端部署优先用 `chip_roi_yolov8_detect_int8.rknn`。
- 云机自动下载 `yolov8n.pt` 可能只得到半截文件，本次出现 `303 KB` 文件导致训练初始化停滞；后续应上传本地已知可用权重并用绝对路径传给 `--model`。
- 云端固定 `batch=64` 在 RTX5090 上稳定，训练 200 epoch 用时约 `0.145 h`，显存峰值约 12 GB。
- RKNN-Toolkit2 2.3.2 推荐在独立 venv 中通过 PyPI 镜像安装；GitHub clone 在云机上可能长时间卡住。
- RKNN-Toolkit2 2.3.2 不能配 `onnx==1.21.0`，需固定 `onnx==1.16.1`，否则 `load_onnx` 会因 `onnx.mapping` 缺失失败。

## chip ROI 运行接入与拍摄参数发现

- 一类 `chip` 模型可以作为第一阶段：全图先找整颗芯片 ROI，再用 ROI 裁剪/居中状态帮助缺陷、字符、引脚等后续类别识别。
- 当前实拍参数 `Light 50%`、`Brightness -6`、`Contrast 1.28`、`Gamma 0.91`、`Saturation 0.30`、`Sharpness 0.85`、`Denoise 6` 符合当前硬件画面：低饱和度抑制偏紫，轻微负亮度和对比度增强表面纹理，锐化提升边缘可见性。
- `Denoise` 不能继续用 `cv2.fastNlMeansDenoisingColored` 逐帧跑实时预览；1280x720 下拖动滑条会导致 GUI 卡死。当前改为轻量双边滤波，并让 denoise 滑条松手后再更新。
- `roi_defect_closed_loop.py` 应优先用训练出的 `chip_roi_yolov8_detect.onnx` 做 ROI，旧暗边缘算法只作为兜底。
- 板端后处理已经支持 YOLOv8 单输出 `OBJ_CLASS_NUM + 4` 通道，因此一类 chip 模型可以通过新增 `OBJ_CLASS_NUM=1` 目标复用现有 C++ 后处理。
- 两阶段实时融合已完成第一版板端闭环：`chip-two-stage-maixcam` 在一个进程内串联 chip ROI INT8 与 defect INT8。
- 原 `chip_roi_yolov8_detect_int8.rknn` 无框根因为单输出 `(1,5,8400)` 同时包含坐标和 score，RKNN INT8 输出使用同一量化尺度，score 精度被 `xywh` 坐标范围吞掉。
- 当前修复方式是把 YOLOv8 detect ONNX 拆成 `yolov8_boxes` 和 `yolov8_scores` 两个输出后重转 RKNN；split-output INT8 的 score scale 约 `0.003786`，`chip-roi-maixcam --conf 0.25` 已可出框。
- C++ 后处理已支持 split-output，并从输出形状推断运行时 class count；同一进程可以同时加载 `class_count=1` 的 chip 模型和 `class_count=4` 的缺陷模型。
- 第一版二阶段输出把 `chip` 作为 class id `0`，缺陷类别整体偏移 `+1`，PC 端 `chip-two-stage-maixcam` profile 使用五类标签。
- 当前 `chip-*` 实时脚本自动下发 WS2812 补光。`chip-two-stage-maixcam` 已默认开启板端 input-adjust：MaixCAM MJPG/YUYV 解码后的 RGB888 会先应用 `Brightness/Contrast/Gamma/Saturation/Sharpness`，再同时送给 chip ROI / defect NPU 和 NV12 回传显示。
- `Denoise` 和 `CLAHE` 不进入板端 NPU 输入；它们最多用于 GUI 人工观察或落盘样本增强。这样可以避免把容易卡顿或代价较高的局部增强塞进实时推理主链路。
- 根据当前硬件条件，RK3576 NPU 主路线应优先 INT8；当前默认实时二阶段路径已经回到 chip ROI INT8 + defect INT8。
- FP RKNN 继续保留为诊断基线，不作为当前默认部署路径。
- 二阶段实时框跳动主要来自 chip ROI crop 微抖和 defect 模型候选不稳定；已加入板端 chip ROI EMA 平滑和 PC 端显示平滑/过滤。当前实拍阈值扫描后建议使用 `--defect-conf 0.45 --defect-confirm 3 --display-max-defects 20`，低阈值只用于诊断召回。
- 二阶段 FPS 主要受每帧双模型 NPU 推理限制：单模型约 `10 FPS`，每帧双模型约 `7 FPS`。默认改为 `chip-interval=3`、`defect-interval=2` 后约 `10.3-10.9 FPS`；静态速度优先可用 `--chip-interval 5 --defect-interval 3` 达到约 `11.3-12.4 FPS`。
- 二阶段 defect 抖动不能只靠 PC 画框平滑解决；板端已在 defect 输出前加入轨迹滤波。默认 `--defect-confirm 2` 要求连续命中后输出，`--defect-hold 3` 在 miss 后保持，`--defect-match-iou 0.10` 与 `--defect-match-center 0.55` 做跨类别物理框匹配，类别用 `--defect-class-decay 0.85` 衰减投票避免 `pinbreak/broken/scratch` 同位置频繁切换。
- `chip_capture_gui` 现在可作为二阶段实时调参与标注入口。GUI 默认启动 `chip-two-stage-maixcam` 等价流，实时显示 chip + defect 框；`Sync view to NPU input` 默认开启后，`Brightness/Contrast/Gamma/Saturation/Sharpness` 会同步到板端 C++ 推理输入，GUI 看到的实时画面就是模型实际吃到的画面。`Denoise/CLAHE` 仍不参与 NPU 输入。
- 板端 input-adjust 的默认参数沿用当前实拍清晰设置：`Brightness -6`、`Contrast 1.28`、`Gamma 0.91`、`Saturation 0.30`、`Sharpness 0.85`。160 帧实测约 `8.3-9.2 FPS`，比未做全帧输入调整时的 `10.3-10.9 FPS` 低；若现场需要速度优先，优先降低或关闭 `Sharpness`。

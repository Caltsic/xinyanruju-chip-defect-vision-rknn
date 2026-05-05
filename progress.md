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

## 2026-05-04 chip 类定位目录规划落档

- 选择仓库根部浅层目录 `chip_roi/` 存放整颗芯片 `chip` 类定位相关文件。
- 新增：
  - `chip_roi/README.md`
  - `chip_roi/dataset_plan.md`
  - `chip_roi/label_rules.md`
- 更新 `.gitignore`，忽略后续生成的大量数据目录：
  - `chip_roi/generated/`
  - `chip_roi/captures/`
  - `chip_roi/review/`
- 更新 `task_plan.md` 和 `findings.md`，记录 chip ROI 数据集阶段、样本量和标注规则。
- 更新 `README.md`，增加 `chip_roi/` 入口说明。

## 2026-05-04 chip 类半自动伪标签与复核 GUI

- 新增脚本：
  - `tools/chip_roi_utils.py`
  - `tools/build_chip_roi_dataset.py`
  - `tools/review_chip_roi_labels.py`
- 已完成语法检查：

```powershell
F:\anaconda\python.exe -m py_compile tools\chip_roi_utils.py tools\build_chip_roi_dataset.py tools\review_chip_roi_labels.py
```

- 已对现有训练集生成候选：

```text
chip_roi/generated/existing_pseudo/manifest.csv
candidate=2406 needs_review=0
```

- 已对筛选后的 MaixCAM 实拍清洁帧生成候选：

```text
chip_roi/generated/captures_pseudo/manifest.csv
candidate=8 needs_review=0
```

- 复核 GUI 命令：

```powershell
F:\anaconda\python.exe .\tools\review_chip_roi_labels.py --manifest .\chip_roi\generated\captures_pseudo\manifest.csv
```

- 预览结论：现有训练集候选框整体可用；实拍图需要继续筛掉诊断/派生图，负样本通过 GUI 的 `Delete` 写空标签。
- 已启动实拍候选复核 GUI，进程号：`18492`。
- 用户反馈接触表黄色框在白底上不清晰；已把预览框改成黑色外描边 + 亮紫色内框，并重建：
  - `chip_roi/generated/existing_pseudo/previews/`
  - `chip_roi/generated/captures_pseudo/previews/`
- 用户反馈 GUI `+/-` 扩缩幅度偏大；已把 `tools/review_chip_roi_labels.py` 默认 `--scale-step` 从 `0.05` 改为 `0.01`，即每次宽高约变化 `2%`。
- 记录旋转框决策：第一版保持 YOLO detect 正框 bbox；旋转框会增加训练格式、NMS、板端后处理和 ROI 裁剪复杂度，后续若需要精细轮廓再升级 oriented bbox 或分割。

## 2026-05-04 chip_capture_gui 一体化实拍标注

- 将 `F:\anaconda\python.exe -m tools.chip_capture_gui` 改为 chip ROI 实拍标注主入口。
- 默认输出目录改为：

```text
chip_roi/generated/gui_capture/
```

- 新增自动按序命名：默认 `chip_0001.jpg`、`chip_0002.jpg`。
- 新增 `Capture ROI`：保存当前清洁帧，自动生成初始 `chip` 框，并写入候选标签/manifest。
- 新增 `Accept` / `Negative`：接受当前框或写空标签。
- 新增 GUI 内调框按钮和键盘快捷键：`A/D/W/S`、`+/-`、`Enter`、`Delete`。
- 主题改为绿色二次元风格，重点提升采集标注时的可读性。
- 关闭窗口和应用退出统一调用 `shutdown()`，退出前等待相机线程停止并关闭补光，降低 `QThread: Destroyed while thread is still running` 风险。

## 2026-05-04 existing_pseudo_800 协作复核任务

- 用户要求将现有训练集复核任务拆分到 `pending` 分支，方便成员协作处理无硬件依赖的标注修正。
- 当前 `chip_roi/generated/existing_pseudo/manifest.csv` 状态：
  - `accepted=8`
  - `candidate=2398`
- 已从未复核 `candidate` 中抽取 `800` 张，生成：

```text
chip_roi/review_tasks/existing_pseudo_800/
```

- 分成 `8` 个 part，每个 `100` 张，成员可以各自认领：

```text
part_001 ... part_008
```

- 每个分片包含独立 `manifest.csv`、`labels/`、`previews/`，路径使用仓库相对路径。
- 已验证 `review_chip_roi_labels.py` 能从分片 manifest 解析相对路径并读取图片/标签。

## 2026-05-04 chip ROI 云端训练准备

- 已拉取 `pending`，当前 HEAD：`024d509 Review chip ROI pseudo labels`。
- 成员复核数据统计：`accepted=754`，`negative=46`。
- GUI 实拍有效纳入：`accepted=375`，`negative=3`；manifest 中 `chip_0288.jpg`、`chip_0313.jpg` 对应图片缺失，未纳入训练包。
- 已生成本地 YOLO 数据集：`chip_roi/generated/cloud_chip_roi_yolo/`。
  - `total_images=1178`
  - `total_objects=1129`
  - `train/valid/test=964/111/103`
  - 训练集空标签负样本 `49`
- 已生成云端训练包：`cloud_training/chip_roi_yolov8_rknn_cloud_package.zip`，大小约 `484 MB`。
- 已上传云机：`/root/autodl-tmp/chip_roi_train_20260504/chip_roi_yolov8_rknn_cloud_package.zip`。
- 远端确认环境：Python `3.12.3`，torch `2.8.0+cu128`，GPU `NVIDIA GeForce RTX 5090`。
- 云端流水线已启动，日志：`/root/autodl-tmp/chip_roi_train_20260504/cloud_run.log`。

## 2026-05-04 chip ROI 云端训练完成

- 云端 `yolov8n.pt` 自动下载出现 303 KB 半截文件，已改为上传本地 `cloud_training/yolov8n.pt` 并用固定 `batch=64` 重启训练。
- YOLOv8n 一类 `chip` 训练完成 200 epoch，best epoch `183`：
  - `precision=0.99946`
  - `recall=1.00000`
  - `mAP50=0.99500`
  - `mAP50-95=0.93583`
- ONNX 导出成功：`outputs/final/chip_roi_yolov8_detect.onnx`，输出形状 `(1, 5, 8400)`。
- RKNN GitHub clone 在云机上卡住；改用独立 `rknn_env` 从 PyPI 镜像安装 `rknn-toolkit2==2.3.2`。
- `onnx==1.21.0` 与 RKNN 2.3.2 不兼容，报 `onnx.mapping` 缺失；固定 `onnx==1.16.1` 后转换成功。
- 已生成并拉回：
  - `cloud_training/chip_roi_outputs_20260504/outputs/final/chip_roi_yolov8_detect.pt`
  - `cloud_training/chip_roi_outputs_20260504/outputs/final/chip_roi_yolov8_detect.onnx`
  - `cloud_training/chip_roi_outputs_20260504/outputs/final/chip_roi_yolov8_detect_fp.rknn`
  - `cloud_training/chip_roi_outputs_20260504/outputs/final/chip_roi_yolov8_detect_int8.rknn`
  - `cloud_training/chip_roi_outputs_20260504/logs/`

## 2026-05-04 chip ROI 运行接入与 GUI 默认参数

- GUI 默认拍摄/预览参数已改为：`Light 50%`、`Brightness -6`、`Contrast 1.28`、`Gamma 0.91`、`Saturation 0.30`、`Sharpness 0.85`、`Denoise 6`。
- `Denoise` 实时路径从慢速 NLM 改为轻量双边滤波，并关闭 denoise 滑条 tracking，避免拖动时 1280x720 预览连续重算导致卡死。
- `tools/roi_defect_closed_loop.py` 已优先使用训练好的 `chip_roi_yolov8_detect.onnx` 定位整颗芯片，失败时回退暗边缘 ROI。
- 闭环输出图新增芯片中心偏移和大小比例辅助线，用于调整芯片位置后再跑缺陷/字符/引脚识别。
- 新增 `chip-roi`、`chip-roi-maixcam` live-view profile。
- 板端源码新增 `rknn_chip_roi_camera_stream`、`rknn_chip_roi_maixcam_stream` CMake target，按 `OBJ_CLASS_NUM=1` 和 `chip_roi_labels.txt` 编译。
- 已把 `chip_roi_yolov8_detect_int8.rknn` 复制到板端源码 model 目录作为本地构建/部署输入；该 `.rknn` 仍按 `.gitignore` 不提交。
- 2026-05-04 已在板端原生编译并安装 `rknn_chip_roi_camera_stream`、`rknn_chip_roi_maixcam_stream`、`chip_roi_labels.txt`、`chip_roi_yolov8_detect_int8.rknn` 和 `chip_roi_yolov8_detect_fp.rknn`。
- 验证结果：INT8 RKNN 能加载但当前 MaixCAM 帧无框；FP RKNN 在 `conf=0.25` 下可实时 `det=1/1`。PC 端 `chip-roi` profile 已临时默认使用 FP RKNN。
- 实时脚本已加入启动前自动预设：`chip-*` profile 默认把 WS2812 设置为 `rgb=190,255,100 brightness=0.50`，并对 PC 端预览/annotated snapshot 套用 `Brightness -6 / Contrast 1.28 / Gamma 0.91 / Saturation 0.30 / Sharpness 0.85 / Denoise 6`。
- 自动预设验证：`--profile chip-roi-maixcam --frames 10 --headless` 成功，输出 `det=3/3`，保存到 `captures/chip_roi_maixcam_auto_setup10_annotated.jpg` 和 `captures/chip_roi_maixcam_auto_setup10_clean.jpg`。

## 2026-05-04 chip ROI 实时部署归档与下一阶段准备

- 新增历史归档：
  - `history/020-chip_roi_realtime_deployment_and_next_stage.md`
- 新增下一阶段施工计划：
  - `plans/chip_roi_two_stage_runtime_plan.md`
- 已更新 `history/000-history-index-and-rules.md`，把 020 作为确认 chip ROI 实时部署、FP/INT8 差异和下一阶段入口的索引。
- 已更新 `task_plan.md`，把后续阶段明确为：
  - 后处理重构：运行时 class count，摆脱单一 `OBJ_CLASS_NUM`
  - 新增两模型板端流：`chip-two-stage-maixcam`
  - 坐标映射：`chip` class id=0，缺陷 class id 整体 +1
  - 稳定性验证：100+ 帧、坏帧跳过、退出释放
  - INT8 修复：ONNX/FP/INT8 对照

## 2026-05-04 INT8 优先规划修正

- 用户明确指出应根据当前硬件条件做选择：RK3576 NPU 上 INT8 性能和部署适配更符合目标，不能因为 FP 已出框就把 FP 作为主线。
- 已新增历史归档：
  - `history/021-int8_first_runtime_plan_correction.md`
- 已修正 `plans/chip_roi_two_stage_runtime_plan.md` 和 `task_plan.md`：
  - 第一优先级改为 chip ROI INT8 诊断：raw/top score、xywh 范围、反量化尺度、阈值和同帧 ONNX/FP/INT8 对照。
  - 第二优先级为修复或重转 chip ROI INT8。
  - 第三优先级才是 INT8 二阶段实时融合：chip ROI INT8 + defect INT8。
  - FP RKNN 保留为诊断基线和临时回退，不作为当前硬件上的默认最终路线。
## 2026-05-04 INT8 split-output 修复与二阶段实时流

- 已确认 `chip_roi_yolov8_detect_int8.rknn` 原无框根因：单输出 `(1, 5, 8400)` 内同时含坐标和 score，RKNN INT8 输出 scale 为 `2.583458`，score 量化精度不足。
- 新增 `tools/split_yolov8_onnx_outputs.py`，把 YOLOv8 detect 输出拆为 `yolov8_boxes` 和 `yolov8_scores`。
- 云端重转并拉回：
  - `cloud_training/chip_roi_outputs_20260504/outputs/final/rknn_split/chip_roi_yolov8_detect_split_int8.rknn`
  - `cloud_training/autodl_outputs_20260502/outputs/final/rknn_split/chipcheck_yolov8_detect_split_int8.rknn`
- 板端 C++ 后处理已支持 split-output，并从模型输出形状推断运行时类别数；同一进程可同时加载 `class_count=1` 的 chip ROI 模型和 `class_count=4` 的 defect 模型。
- 已部署：
  - `/userdata/rknn_yolo11_demo/model/chip_roi_yolov8_detect_split_int8.rknn`
  - `/userdata/rknn_yolo11_demo/model/chipcheck_yolov8_detect_split_int8.rknn`
  - `/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream`
- `chip-roi-maixcam --conf 0.25 --frames 20 --headless` 验证通过，输出 `det=4/4`，截图：
  - `captures/chip_roi_split_int8_annotated.jpg`
- `chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.25 --frames 12 --headless` 验证通过，输出约 `6.9 FPS`、`det=7/7`，截图：
  - `captures/chip_two_stage_maixcam_int8_conf25_annotated.jpg`
- 同配置 `--frames 100 --headless` 稳定性验证通过，`Processed frames: 100`，实时约 `7.1-7.3 FPS`。
- `defect_conf=0.05` 可用于低阈值诊断，但当前实拍分布会产生大量大框假阳性；第一版 demo 默认建议从 `0.25` 起步。

## 2026-05-04 二阶段实时流复核

- 已把 `task_plan.md` 中旧的 INT8/二阶段 pending 状态收口为 complete，并同步更新 `findings.md` 与 `plans/chip_roi_two_stage_runtime_plan.md`。
- Python 语法检查通过：

```powershell
F:\anaconda\python.exe -m py_compile .\tools\adb_imx415_rknn_live_view.py .\tools\split_yolov8_onnx_outputs.py .\tools\roi_defect_closed_loop.py
```

- 本地确认四个 split INT8 关键产物存在：

```text
rknn_work/board_yolo11_src/examples/yolo11/model/chip_roi_yolov8_detect_split_int8.rknn
rknn_work/board_yolo11_src/examples/yolo11/model/chipcheck_yolov8_detect_split_int8.rknn
cloud_training/chip_roi_outputs_20260504/outputs/final/rknn_split/chip_roi_yolov8_detect_split_int8.rknn
cloud_training/autodl_outputs_20260502/outputs/final/rknn_split/chipcheck_yolov8_detect_split_int8.rknn
```

- 板端 30 帧复核通过：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 30 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.25 --remote-log /tmp/chip_two_stage_recheck.log
```

- 输出摘要：

```text
Runtime setup: WS2812 rgb=190,255,100 brightness=0.50
frame=0 fps=0.0 focus=113 size=1280x720 det=6/6
frame=28 fps=6.7 focus=113 size=1280x720 det=6/6
Processed frames: 30
model class count=1
model class count=4
```

## 2026-05-04 二阶段实时框稳定化

- 用户反馈二阶段实时窗口中除 `chip` 类外标示框跳动严重，难以观察。
- 判断：这是 ROI crop 微抖、defect 模型候选不稳定和低阈值多框叠加的问题，不是 INT8 链路失效。
- 板端 `live_camera_yolo.cc` 已新增 chip ROI EMA 平滑并重新编译部署：
  - `--roi-smooth-alpha` 默认 `0.35`
  - `--roi-hold` 默认 `3`
- PC 端 `tools/adb_imx415_rknn_live_view.py` 已新增显示平滑和过滤：
  - `chip-two-stage-maixcam` 默认开启短时显示平滑。
  - 默认 `--smooth-hold 2`、`--smooth-min-hits 2`。
  - 默认对二阶段显示做跨类别 NMS，`--display-max-defects 4`、`--display-nms 0.30`。
  - 可用 `--no-smooth-boxes --no-display-filter` 查看原始逐帧输出。
- 验证 60 帧默认平滑通过，截图：
  - `captures/chip_two_stage_smooth_filtered_annotated.jpg`
  - `captures/chip_two_stage_smooth_filtered_clean.jpg`
- 当前更适合观察的命令为：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3
```

- 该命令 60 帧验证通过，截图：
  - `captures/chip_two_stage_smooth_conf35_annotated.jpg`
  - `captures/chip_two_stage_smooth_conf35_clean.jpg`
- 已新增历史归档：
  - `history/023-two_stage_temporal_stabilization.md`

## 2026-05-04 二阶段 FPS 节奏优化

- 用户反馈二阶段实时约 `7 FPS`，观感接近 PPT。
- 基线测试：
  - `chip-roi-maixcam` 单模型约 `9.6-10.3 FPS`。
  - `chip-defect-maixcam` 单模型约 `9.4-10.0 FPS`。
  - 二阶段每帧双模型约 `6.5-7.0 FPS`。
- 判断：主要瓶颈是每帧连续跑 chip ROI INT8 与 defect INT8 两次 NPU，PC 预览参数不是主瓶颈。
- 板端新增二阶段推理节奏参数：
  - `--chip-interval`，默认 `3`
  - `--defect-interval`，默认 `2`
- PC 端 `adb_imx415_rknn_live_view.py` 已同步传参。
- 默认优化节奏 160 帧验证通过：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 160 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3
```

输出速度约 `10.3-10.9 FPS`。

- 速度优先静态场景验证通过：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 160 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3 --chip-interval 5 --defect-interval 3
```

输出速度约 `11.3-12.4 FPS`。

- 已新增历史归档：
  - `history/024-two_stage_fps_cadence_optimization.md`

## 2026-05-04 二阶段 defect 板端时序滤波

- 用户确认核心问题是缺少对缺陷结果的时序滤波，需要在板端结果输出前处理，而不只是 PC 端画框平滑。
- 板端 `live_camera_yolo.cc` 已新增 `DefectTemporalFilter`：
  - 每个 defect 框默认需要连续命中 `2` 次才输出：`--defect-confirm 2`。
  - 缺失后默认保持 `3` 次 defect 更新：`--defect-hold 3`。
  - 坐标/置信度默认 EMA：`--defect-smooth-alpha 0.35`。
  - 同类/跨类候选使用 IoU + 中心距离做轨迹匹配：`--defect-match-iou 0.10`、`--defect-match-center 0.55`。
  - 类别使用衰减投票和切换滞后，降低 `pinbreak/broken/scratch` 同位置来回抢框。
- PC 端 `tools/adb_imx415_rknn_live_view.py` 已同步透传上述板端参数。
- 板端已重新编译并安装 `/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream`。
- 验证时关闭 PC 端平滑/过滤，确认板端参数生效并跑通 `160` 帧：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 160 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --defect-confirm 2 --defect-hold 3 --no-smooth-boxes --no-display-filter --save-snapshot .\captures\chip_two_stage_board_filter_annotated.jpg --save-clean-snapshot .\captures\chip_two_stage_board_filter_clean.jpg --remote-log /tmp/chip_two_stage_board_filter.log
```

- 输出速度约 `9.5-11.5 FPS`，截图：
  - `captures/chip_two_stage_board_filter_annotated.jpg`
  - `captures/chip_two_stage_board_filter_clean.jpg`
- 已新增历史归档：
  - `history/025-two_stage_board_defect_temporal_filter.md`

## 2026-05-05 chip_capture_gui 二阶段实时调参

- 用户希望复用 `F:\anaconda\python.exe -m tools.chip_capture_gui`，保留拍照标注，并加入等价于当前二阶段实时命令的检测显示，用于快速比较引脚、丝印、破损在不同画面参数下的可见性。
- `tools/chip_capture_gui/settings.py` 已把 GUI 默认相机流切到：

```text
profile=chip-two-stage-maixcam
remote_binary=./rknn_chip_two_stage_maixcam_stream
remote_model=model/chip_roi_yolov8_detect_split_int8.rknn
conf=0.25
chip_conf=0.25
defect_conf=0.35
display_max_defects=3
```

- `tools/chip_capture_gui/app.py` 已新增 `Mode` 区：
  - `Live Detect`：显示 chip + defect 检测框。
  - `Capture / Label`：关闭检测框，保留采集标注流程。
  - `Draw detection boxes`：单独开关检测框。
  - `Save adjusted capture`：默认保存当前高级选项处理后的画面。
- `Capture ROI` 现在优先使用板端二阶段 `chip` 框作为初始 ROI，失败时再回退暗区域/边缘 ROI。
- 高级选项新增快速预设：
  - `Pins`
  - `Text`
  - `Damage`
  - `Reset`
- 元数据新增 `capture_adjusted`，并继续记录完整 `image_adjust` 参数。
- 验证：
  - `py_compile` 通过。
  - 远端命令构造确认启动 `rknn_chip_two_stage_maixcam_stream`。
  - GUI 相机类短帧取流通过，`1280x720`，检测结果可读，速度约 `9-13 FPS`。
- 已新增历史归档：
  - `history/026-chip_capture_gui_two_stage_live_tuning.md`

## 2026-05-05 板端 NPU 输入与显示画面一致

- 用户要求 MaixCAM 链路改为：`MJPG -> 板端解码 RGB888 -> 板端应用同一套图像调整参数 -> 调整后的 RGB888 给 chip ROI / defect NPU -> 调整后的画面回传 PC 显示`。
- `rknn_work/board_yolo11_src/examples/yolo11/cpp/live_camera_yolo.cc` 已新增板端 `input_adjust`：
  - `--input-adjust` / `--no-input-adjust`
  - `--input-brightness`
  - `--input-contrast`
  - `--input-gamma`
  - `--input-saturation`
  - `--input-sharpness`
  - `--input-adjust-file`
- 板端算法边界：
  - `Brightness/Contrast/Gamma` 合成 256 项 LUT。
  - `Saturation` 使用 RGB luma-blend，不做 HSV 转换。
  - `Sharpness` 使用轻量 luma unsharp，可通过 `--input-sharpness 0` 关闭。
  - `Denoise` 和 `CLAHE` 不进入板端 NPU 输入。
- `tools/adb_imx415_rknn_live_view.py` 已默认让 `chip-two-stage-maixcam` 开启板端 input-adjust，并在开流前写入 `/tmp/chip_input_adjust.conf`。PC 端显示不再重复套同一套预览增强。
- `tools/chip_capture_gui` 已新增 `Sync view to NPU input` 开关，默认开启；高级参数变化会同步写入板端配置文件，使 GUI 看到的实时画面与 NPU 输入一致。
- 默认同步参数保持为当前实拍清晰设置：

```text
Light 50%
Brightness -6
Contrast 1.28
Gamma 0.91
Saturation 0.30
Sharpness 0.85
Denoise 6 仅保留为 GUI 观察/落盘参数，不进 NPU 输入
```

- 已重新编译并安装：

```text
/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream
```

- 160 帧验证通过：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 160 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3 --save-snapshot .\captures\chip_two_stage_input_adjust_fast_annotated.jpg --save-clean-snapshot .\captures\chip_two_stage_input_adjust_fast_clean.jpg --remote-log /tmp/chip_two_stage_input_adjust_fast.log
```

- 板端日志确认：

```text
input_adjust=on brightness=-6 contrast=1.280 gamma=0.910 saturation=0.300 sharpness=0.850 adjust_file=/tmp/chip_input_adjust.conf
```

- 当前默认二阶段加板端输入调整后约 `8.3-9.2 FPS`，低于未做全帧输入调整时的 `10.3-10.9 FPS`。主要成本来自 1280x720 全帧 RGB 预处理和锐化；若现场优先速度，可把 `Sharpness` 降低或设为 `0`。
- 已新增历史归档：
  - `history/027-board_input_adjust_matches_display.md`

## 2026-05-05 二阶段显示阈值实拍调试

- 用户反馈一类标示框看起来像最多只能出现两个，希望改成选择合适置信度阈值，超过阈值就稳定显示。
- 代码确认：
  - `chip` 类在二阶段中仍只选最高置信度的一颗芯片 ROI，这是当前单芯片二阶段定位设计。
  - defect 类没有“每类最多两个”的板端限制；原先观感来自 PC/GUI 显示端 `display_max_defects` 总量上限和跨类显示 NMS。
- 用当前 MaixCAM 实拍画面关闭显示端过滤做阈值扫描：
  - `0.20-0.35`：召回多，但 pinbreak/scratch 临界框较多。
  - `0.50`：开始明显漏掉当前破损芯片上的稳定 broken 候选。
  - `0.45 + defect_confirm=3`：当前画面较平衡，`chip` 稳定约 `0.90+`，`broken/pinbreak` 主要稳定框约 `0.5-0.6`。
- 默认策略已改为：

```text
defect_conf=0.45
defect_confirm=3
display_max_defects=20
```

- `--display-max-defects 0` 现在表示保留显示 NMS 但不做数量截断；日常默认 `20` 基本等价于不靠 top-k 限制。
- 验证命令：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 120 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20 --save-snapshot .\captures\chip_two_stage_conf045_confirm3_annotated.jpg --save-clean-snapshot .\captures\chip_two_stage_conf045_confirm3_clean.jpg --remote-log /tmp/chip_two_stage_conf045_confirm3.log
```

- 结果：`120` 帧通过，末帧 `det=5/5`、约 `8.4 FPS`，截图：
  - `captures/chip_two_stage_conf045_confirm3_annotated.jpg`
  - `captures/chip_two_stage_conf045_confirm3_clean.jpg`

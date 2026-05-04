# Astra Pro Plus 芯片检测开发计划

更新时间：2026-05-03

## 目标

在不依赖 IMX415/CSI/RKISP 的前提下，使用 Astra Pro Plus 的 RGB UVC 相机作为输入源，复用当前已部署的 YOLOv8 芯片缺陷 RKNN 模型，跑通板端 NPU 检测 demo，并通过现有 ADB RYL1 协议回传到 PC 显示/保存截图。

## 范围

- 只使用 Astra RGB：`/dev/video73`。
- 暂不接入深度：`2bc5:060f ORBBEC Depth Sensor` 需要奥比私有 OpenNI/Orbbec 驱动，且对当前细小表面缺陷帮助有限。
- 保留现有 IMX415 程序：`rknn_chip_defect_camera_stream` 不作为第一步改动目标。
- 新增独立 Astra 目标，便于回退和对比。

## 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1. 最小硬件验证 | complete | Astra 已枚举，RGB UVC 可抓图，深度暂不可用 |
| 2. 计划和发现落盘 | complete | 创建 `task_plan.md`、`findings.md`、`progress.md` |
| 3. 代码适配 | complete | 新增 Astra RGB/YUYV 采集入口，复用 RKNN 推理和后处理 |
| 4. 板端部署 | complete | 编译并安装新二进制到 `/userdata/rknn_yolo11_demo` |
| 5. 冒烟验证 | complete | 运行 Astra 芯片检测并保存 annotated/clean 截图 |

## 技术路线

优先路线：`/dev/video73` 使用 `640x480 YUYV @ 30fps`，在 C++ 中用 V4L2 单平面采集，转换为 RGB888，letterbox 到模型 `640x640` 输入，再复用当前 RKNN 推理与 YOLOv8 后处理。

备选路线：使用 `MJPG` 高分辨率输入，借助本地已有 jpeg/turbo 或 OpenCV 解码。该路线画面更细，但先不作为最小 demo 的第一步，避免新增解码复杂度。

## 风险

- Astra RGB 是固定焦距广角相机，不适合近距离微小划痕，模型可能输出 `det 0/0`。
- 现有缺陷模型训练分布偏近距离芯片缺陷图，Astra 桌面远景分布差异大。
- USB2.0 + Hub 下高分辨率 MJPG 可用，但 YUYV 高分辨率帧率低；最小 demo 使用 `640x480 YUYV` 保守起步。
- 当前 git 工作区已有多处未提交改动，Astra 改动需保持独立，避免回滚既有内容。

## 完成标准

- 板端存在新的 Astra 检测二进制：`rknn_chip_defect_demo`、`rknn_chip_defect_astra_stream`。
- PC 端能通过现有 `tools/adb_imx415_rknn_live_view.py` 参数覆盖命令收到 Astra 帧。
- 已保存 Astra clean frame 和 annotated frame。
- 当前检测结果为 `det 0/0`，日志显示采集、RGA letterbox 和 `rknn_run` 均正常，属于“推理正常但无框”。

## 当前结果

已跑通：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py `
  --remote-binary ./rknn_chip_defect_astra_stream `
  --device /dev/video73 --width 640 --height 480 --fps 30 --skip 3 `
  --frames 5 --headless `
  --save-snapshot .\captures\astra_chip_live_annotated.jpg `
  --save-clean-snapshot .\captures\astra_chip_live_clean.jpg
```

输出：

```text
Processed frames: 5
det=0/0
```

## 追加计划：MaixCAM 芯片 ROI + 轻量预处理最小闭环

更新时间：2026-05-04

### 背景

MaixCAM 全画面中芯片和缺陷目标占比偏小，直接全图送当前缺陷模型时，破损处响应接近 0；同一画面裁出芯片 ROI 后，ONNX 能给出可用的 `broken` 置信度。因此下一步先做 PC 端最小闭环，验证 ROI 和轻量预处理策略，再决定是否下沉到板端 RKNN/C++。

### 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1. 规划落档 | complete | 记录两阶段路线：全图找 chip ROI，再在 ROI 上跑缺陷模型 |
| 2. 自动 ROI | complete | 使用暗区域 + 边缘 + 中心先验自动定位当前芯片 ROI |
| 3. 轻量预处理 | complete | 默认 `raw` 与 `light_gamma_clahe` 两路，避免强白平衡导致类别漂移 |
| 4. 本地 ONNX 闭环 | complete | 新增 `tools/roi_defect_closed_loop.py`，检测框可映射回原图 |
| 5. 当前画面验证 | complete | 静态实拍图与 `--capture-maixcam` 抓帧模式均跑通 |
| 6. 板端化 | pending | 后续把 ROI/preprocess 逻辑移入 `rknn_chip_defect_maixcam_stream` 或新增二进制 |

### 当前策略

最小闭环先不训练新模型：

```text
MaixCAM 全图
 -> 自动定位 chip ROI
 -> ROI 加 margin 后裁剪
 -> raw + light_gamma_clahe 两路 ONNX 推理
 -> 合并/NMS
 -> 检测框映射回原图
```

后续训练路线：

- 现有训练集可用于自动生成 `chip` 伪标签，训练 1 类芯片定位模型。
- 缺陷模型最好继续保留 `raw` 分支，并在训练增强中加入部署侧的轻量对比度/亮度变化。
- 不建议只靠强预处理弥补尺度差异；ROI/尺度是第一优先级。

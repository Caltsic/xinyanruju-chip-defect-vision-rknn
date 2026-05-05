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

## 追加计划：chip 类定位数据集

更新时间：2026-05-04

### 背景

当前缺陷模型没有整颗 `chip` 类，不能直接在全图中框出芯片。实拍画面里芯片占比偏小，导致破损点直接全图推理时置信度接近 0；先训练 1 类 `chip` 定位模型，可以把全图转成尺度合适的芯片 ROI，再复用现有缺陷模型。

### 目录决策

使用仓库根目录下的浅层目录：

```text
chip_roi/
```

该目录只提交规划、规则、少量配置；大批量图片、伪标签、预览图和采集结果放入 ignored 子目录：

```text
chip_roi/generated/
chip_roi/captures/
chip_roi/review/
```

### 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1. 目录和规则落档 | complete | 新增 `chip_roi/README.md`、`dataset_plan.md`、`label_rules.md` |
| 2. 现有训练集伪标签 | complete | 已生成 `2406` 张候选，输出到 `chip_roi/generated/existing_pseudo/` |
| 3. 人工抽检修正 | in_progress | 已新增轻量 OpenCV GUI，支持 A/D/W/S、+/-、Enter、Delete |
| 4. 硬件实拍补集 | in_progress | `tools.chip_capture_gui` 已集成实拍、自动编号、自动 chip 框、Accept/Negative |
| 5. 第一版 chip 模型训练 | pending | 训练轻量 1 类 ROI 模型 |
| 6. 两阶段实时闭环 | pending | 全图找 chip ROI，再跑当前缺陷模型 |

### 样本起步量

- 现有训练集伪标签：`1000-2000` 张。
- 人工复核：`100-200` 张。
- 当前硬件实拍正样本：`300-600` 张。
- 负样本：`100-200` 张。
- 多芯片/截断样本：`50-100` 张。

### 已执行命令

```powershell
F:\anaconda\python.exe .\tools\build_chip_roi_dataset.py existing `
  --output .\chip_roi\generated\existing_pseudo `
  --preview-limit 160 --progress-every 250

F:\anaconda\python.exe .\tools\build_chip_roi_dataset.py captures .\captures `
  --include maixcam `
  --exclude annotated,variants,crop,onnx_diag,contact,preview,smoke,out,top2,confidence,uvc,roi_closed_loop,conf `
  --output .\chip_roi\generated\captures_pseudo `
  --preview-limit 80
```

输出：

```text
existing_pseudo: 2406 candidate, 0 needs_review
captures_pseudo: 8 candidate, 0 needs_review
```

### GUI 实拍入口

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui
```

默认输出：

```text
chip_roi/generated/gui_capture/
```

GUI 会自动生成 `chip_0001.jpg` 形式的顺序文件名；`Capture ROI` 自动保存图像和初始 `chip` 框，`Accept`/`Negative` 写入最终标签状态。

## 追加计划：chip ROI YOLOv8 云端训练
更新时间：2026-05-04

### 背景

成员已在 `pending` 分支完成第一批 `existing_pseudo_800` 复核，本地 GUI 实拍也已形成一批 chip ROI 标签。当前进入第一版一类 `chip` 定位模型训练阶段，用于支撑后续“全图找 chip ROI -> ROI 内跑缺陷模型”的二阶段闭环。

### 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1. 拉取协作标注 | complete | 已 fast-forward 到 `024d509 Review chip ROI pseudo labels` |
| 2. 构建本地 YOLO 数据集 | complete | `chip_roi/generated/cloud_chip_roi_yolo/`，1178 张图、1129 个 chip 框、49 张负样本 |
| 3. 构建云端训练包 | complete | `cloud_training/chip_roi_yolov8_rknn_cloud_package.zip` |
| 4. 上传云机 | complete | 远端目录 `/root/autodl-tmp/chip_roi_train_20260504/` |
| 5. 云端训练与 ONNX 导出 | complete | RTX5090，YOLOv8n，imgsz 640，epochs 200，batch 64，best epoch 183 |
| 6. RKNN FP/INT8 转换 | complete | 独立 `rknn_env`，`rknn-toolkit2==2.3.2`，`onnx==1.16.1`，目标 `rk3576` |
| 7. 拉回产物 | complete | 已拉回 PT/ONNX/FP RKNN/INT8 RKNN/报告/日志到 `cloud_training/chip_roi_outputs_20260504/` |

### 关键决策

- 第一版只训练一类 `chip` 正框，不和缺陷类混训。
- 负样本使用空标签 `.txt`；当前负样本原图分组不足 10 组，先全部放在训练集，后续补真实无芯片负样本再评估误检。
- RKNN-Toolkit2 放在训练和 ONNX 导出之后安装，避免提前改动 PyTorch 2.8 + CUDA 12.8 训练环境。
- 板端优先部署 `chip_roi_yolov8_detect_int8.rknn`，保留 ONNX 和 FP RKNN 做排查基线。

### 协作复核拆分

已拆分第一批硬件无关复核任务：

```text
chip_roi/review_tasks/existing_pseudo_800/
```

- 总量：`800` 张。
- 分片：`8` 个 part，每个 `100` 张。
- 运行方式：

```powershell
F:\anaconda\python.exe .\tools\review_chip_roi_labels.py --manifest .\chip_roi\review_tasks\existing_pseudo_800\part_001\manifest.csv
```

成员只修改自己认领的 `part_xxx`，避免多人改同一 manifest。

## 追加计划：chip ROI 运行接入与默认拍摄参数
更新时间：2026-05-04

### 背景

第一版 `chip` 一类模型已经训练并产出 ONNX/INT8 RKNN。当前可以先把它作为全图第一阶段定位模型，用于辅助芯片居中和尺寸调整，再为缺陷、字符、引脚等后续模型提供稳定 ROI。用户确认当前实拍画面在 `Light 50%`、`Brightness -6`、`Contrast 1.28`、`Gamma 0.91`、`Saturation 0.30`、`Sharpness 0.85` 时芯片表面更清晰，同时补充 `Denoise` 调整会卡死，应保持默认 `6`。

### 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1. GUI 默认参数 | complete | `ImageAdjustSettings` 和补光默认值已更新 |
| 2. Denoise 卡顿处理 | complete | 实时预览改轻量双边滤波，denoise 滑条松手后更新 |
| 3. PC 侧 chip ROI 闭环 | complete | `roi_defect_closed_loop.py` 优先用 chip ONNX，失败回退暗边缘 ROI |
| 4. chip-only 板端入口 | complete | 新增并部署 `chip-roi` / `chip-roi-maixcam` profile 和 CMake target |
| 5. INT8 chip ROI 排查 | complete | 原单输出 INT8 的无框根因为 `xywh`/`score` 共用量化尺度；已用 split-output INT8 修通 |
| 6. 两阶段板端融合 | complete | 已新增并部署 `chip-two-stage-maixcam`，一个进程内串联 chip ROI INT8 与 defect INT8 |

### 当前命令

PC 侧单帧两阶段验证：

```powershell
F:\anaconda\python.exe .\tools\roi_defect_closed_loop.py --capture-maixcam --save-dir .\captures\roi_defect_closed_loop_capture
```

板端 chip-only 实时显示，当前 profile 仍可通过已验证可出框的 FP RKNN 做诊断对照；面向 RK3576 NPU 的正确主线是先修通 INT8：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-roi-maixcam --conf 0.25
```

### 关键决策

- 拍摄默认参数可以采用用户现场确认的清晰配置，但最终仍以模型输出稳定性作为验收标准。
- 当前新增 chip-only 实时入口，不直接替换缺陷模型默认 profile，避免未部署新二进制时影响现有实时缺陷链路。
- `Denoise 6` 保留为默认值，但不能使用慢速 NLM 实时逐帧处理。
- INT8 RKNN 是当前硬件的目标部署形态；MaixCAM 实测无框不是绕开的理由，而是下一阶段第一优先级。FP RKNN 只作为同帧诊断基线和临时回退。

## 追加计划：chip ROI 二阶段实时融合
更新时间：2026-05-04

### 背景

chip-only FP 基线已经证明 MaixCAM 当前画面、chip 模型和板端流链路本身可以出框，且实时启动会自动设置补光和 PC 端预览参数。由于当前硬件是 RK3576 NPU，下一阶段应先修通 chip ROI INT8，再把“全图找 chip ROI -> ROI 内跑缺陷模型”迁入板端，形成 INT8 二阶段实时闭环。

详细实施计划见：

```text
plans/chip_roi_two_stage_runtime_plan.md
```

### 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1. 运行归档 | complete | `history/020-chip_roi_realtime_deployment_and_next_stage.md` |
| 2. INT8 优先规划修正 | complete | `history/021-int8_first_runtime_plan_correction.md` |
| 3. INT8 诊断插桩 | complete | 板端日志确认原单输出 `scale=2.583458`，score 精度被坐标范围吞掉 |
| 4. 同帧三路对照 | complete | ONNX/FP 基线可出框，原 INT8 无框；split-output INT8 已恢复 chip ROI 出框 |
| 5. INT8 修复或重转 | complete | 在云端把 chip ROI 与 defect ONNX 拆成 boxes/scores 两输出并重转 INT8 |
| 6. 后处理重构 | complete | C++ 后处理支持 split-output，并从输出形状推断运行时 class count |
| 7. INT8 两模型板端流 | complete | 新增 `chip-two-stage-maixcam` target/profile，默认 chip ROI INT8 + defect INT8 |
| 8. 坐标映射与稳定性验证 | complete | chip class id=0、缺陷 class id +1；100 帧 headless 稳定验证通过 |

### 下一步施工原则

- INT8 优先：RK3576 NPU 的目标路径应是 chip ROI INT8 + defect INT8，先修 chip ROI INT8 无框问题。
- FP 只做诊断：FP RKNN 用于证明模型/摄像头分布/流链路可行，并在同帧对照里定位 INT8 差异，不作为默认施工路线。
- 有界回退：只有 INT8 诊断完成后仍无法短期修复时，才允许用 FP 临时验证二阶段架构，且必须保留回切 INT8 的待办。
- 不把 PC 端预览参数直接等同于 NPU 输入参数；只有实测提升后才迁入板端 C++ 预处理。
- 第一版仍使用 bbox，不引入 segmentation、rotated bbox 或缺陷级 mask。
## 2026-05-04 INT8 split-output 与二阶段实时流

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1. INT8 无框根因 | complete | 原单输出 YOLOv8 RKNN 把 `xywh` 和 `score` 共用 INT8 scale，score 精度被坐标范围吞掉 |
| 2. split ONNX/RKNN | complete | 已生成 chip ROI 与 defect 的 split-output ONNX/FP/INT8 RKNN |
| 3. 板端二输出后处理 | complete | C++ 后处理支持 `yolov8_boxes` + `yolov8_scores`，并按输出形状推断运行时 class count |
| 4. chip ROI INT8 实时 | complete | `chip-roi-maixcam --conf 0.25` 已实时出框，`scores scale=0.003786` |
| 5. 二阶段板端流 | complete | 新增并部署 `rknn_chip_two_stage_maixcam_stream` / `chip-two-stage-maixcam` |
| 6. 二阶段阈值整理 | complete | `defect_conf=0.05` 仅用于诊断；第一版 demo 默认建议从 `0.25` 起步 |
| 7. defect 板端时序滤波 | complete | 已加入连续命中、miss 保持、跨类别匹配和类别投票，降低缺陷框闪烁 |

当前二阶段命令：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3
```

诊断归档：

```text
history/022-int8_split_output_and_two_stage_runtime.md
history/025-two_stage_board_defect_temporal_filter.md
```

## 追加计划：chip_capture_gui 集成二阶段实时检测与调参采集
更新时间：2026-05-05

### 背景

当前二阶段实时检测效果已经可用，但引脚清晰度仍需现场快速调参。需要复用 `F:\anaconda\python.exe -m tools.chip_capture_gui`，保留原有拍照标注能力，同时在 GUI 内直接显示等价于以下命令的二阶段实时检测：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3
```

### 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1. GUI 相机设置补齐二阶段参数 | complete | `CameraSettings` 已默认使用 `chip-two-stage-maixcam` 等价参数 |
| 2. GUI 实时显示模式 | complete | 已新增 Capture/Live Detect 切换和检测框显示控制 |
| 3. 当前调参画面落盘标注 | complete | Capture ROI 默认保存当前高级选项处理后的画面，并记录参数 |
| 4. 验证与落档 | complete | py_compile、远端命令构造和短帧取流验证均通过 |

### 关键决策

- 该阶段最初只把高级选项作用在 PC 端预览和采集落盘图；后续已由“板端 NPU 输入与实时显示画面一致”方案取代，二阶段 MaixCAM 实时链路默认同步到板端 NPU 输入。
- GUI 默认二阶段检测使用 chip ROI INT8 + defect INT8。
- 采集标注样本应记录 `Brightness/Contrast/Gamma/Saturation/Sharpness/Denoise/CLAHE`，方便后续比较引脚、丝印、破损各自适合的预处理。
- `Denoise/CLAHE` 仍只作为人工观察或落盘辅助，不进入板端 NPU 输入；`Brightness/Contrast/Gamma/Saturation/Sharpness` 已迁入板端 C++ 预处理。

## 追加计划：板端 NPU 输入与实时显示画面一致
更新时间：2026-05-05

### 背景

用户确认希望通过实时识别准确率判断不同画面参数对引脚、丝印、破损等类别的帮助，因此板端 NPU 输入必须和 PC/GUI 看到的画面一致。已把 MaixCAM MJPG/YUYV 解码后的 RGB888 先经过同一套轻量图像调整，再同时送给 chip ROI / defect NPU 和 NV12 回传显示。

### 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1. 方案定界 | complete | 仅纳入 Brightness/Contrast/Gamma/Saturation/Sharpness，不纳入 Denoise/CLAHE |
| 2. 板端轻量 RGB888 预处理 | complete | MJPG/YUYV 解码后先调整 RGB888，再给 NPU 和 NV12 回传 |
| 3. PC/GUI 参数透传 | complete | 实时脚本和 GUI 统一下发 `/tmp/chip_input_adjust.conf` 与 `--input-*` 参数 |
| 4. 部署验证 | complete | 已编译安装板端二阶段二进制，160 帧验证通过，日志确认 `input_adjust=on` |
| 5. 落档 | complete | 更新 README、history、progress、findings |

### 关键决策

- `Denoise` 和 `CLAHE` 不进入板端 NPU 输入预处理；二者最多保留为人工观察辅助。
- 亮度/对比度/gamma 合成为 256 项 LUT，降低每帧成本。
- 饱和度使用 RGB 空间的 luma-blend，避免 HSV 转换成本。
- 锐化使用轻量 3x3 unsharp，并允许 `--input-sharpness 0` 关闭。
- 对 NV12/IMX415 路径暂不强行转换；当前目标优先覆盖 MaixCAM MJPG/YUYV 的 RGB888 路径。
- 默认参数沿用当前实拍清晰设置：`Brightness -6`、`Contrast 1.28`、`Gamma 0.91`、`Saturation 0.30`、`Sharpness 0.85`；实测二阶段默认约 `8.3-9.2 FPS`，若优先速度可降低或关闭 `Sharpness`。

## 追加计划：二阶段 defect 显示阈值与数量限制修正
更新时间：2026-05-05

### 背景

用户反馈标示框看起来像被限制为少量 top-k，希望改成合适置信度阈值以上稳定显示。当前二阶段 `chip` 类仍只取一颗芯片 ROI；defect 类不应被低显示上限误伤。

### 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1. 限制来源确认 | complete | 板端 defect 无每类两个限制；显示端 `display_max_defects` 和 NMS 造成 top-k 观感 |
| 2. 当前画面阈值扫描 | complete | 扫描 `0.20-0.50`，确认 `0.45 + defect_confirm=3` 当前较平衡 |
| 3. 默认参数修正 | complete | `defect_conf=0.45`、`defect_confirm=3`、`display_max_defects=20` |
| 4. 验证与归档 | complete | 120 帧验证通过，归档 `history/028-two_stage_threshold_display_tuning.md` |

### 关键决策

- `display_max_defects=20` 用于避免日常观察被 top-k 限制；`--display-max-defects 0` 表示保留显示 NMS 但不做数量截断。
- `defect_conf=0.45` 是当前实拍破损芯片画面的平衡点；`0.50` 已开始漏 broken，`0.35` 以下更适合诊断召回。
- `defect_confirm=3` 比 `2` 更偏稳定，代价是新缺陷框出现稍慢。

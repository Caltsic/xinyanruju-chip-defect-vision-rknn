# chip 类定位工作区

`chip_roi/` 用于放置整颗芯片 `chip` 类定位相关的轻量文件。它和现有缺陷模型分开管理：缺陷模型继续识别 `broken`、`pinbreak`、`scratch` 等缺陷，`chip` 模型只负责先从全画面里找到芯片 ROI。

## 目录边界

- `README.md`：本目录入口和约定。
- `dataset_plan.md`：chip 类数据集构建和训练规划。
- `label_rules.md`：chip bbox 标注规则。
- `generated/`：后续脚本生成的 YOLO 数据集、伪标签、预览图，默认不入 git。
- `captures/`：后续硬件实拍原图批次，默认不入 git。
- `review/`：后续人工复核导出的接触表、待修正样本，默认不入 git。

当前只提交文档和规则，不直接提交大量图片、标签或训练产物。

## 模型目标

第一版目标是训练一个 1 类检测模型：

```text
0: chip
```

推理链路建议保持两阶段：

```text
全图 -> chip 定位模型 -> 芯片 ROI 裁剪/缩放 -> 现有缺陷模型 -> 缺陷框映射回原图
```

这样可以先解决当前实拍画面里芯片占比太小的问题，避免把整张 `1280x720` 画面直接送入缺陷模型。

## 样本起步量

建议第一版不要追求大而全，先做能闭环的数量：

- 现有训练集自动伪标签：`1000-2000` 张，抽检修正其中 `100-200` 张。
- 当前硬件实拍正样本：`300-600` 张，覆盖 MaixCAM、IMX415/Astra 可用输入、不同补光和角度。
- 负样本：`100-200` 张，包括空载板、桌面、夹具、包装、局部文字/引脚但没有完整芯片的画面。
- 多芯片样本：第一版 `50-100` 张足够，用来验证多目标时不会只框一个。

如果第一版在当前工位上 ROI 稳定，再扩到更多芯片封装、背景和光照。

## 后续脚本约定

后续脚本建议写入：

```text
chip_roi/generated/dataset/
chip_roi/generated/previews/
chip_roi/captures/
chip_roi/review/
```

这些目录由 `.gitignore` 忽略。需要保留的规则、配置和小型样例再单独提交。

## 半自动生成与复核

已新增两个工具：

```text
tools/build_chip_roi_dataset.py
tools/review_chip_roi_labels.py
```

对现有训练集生成 `chip` 伪标签：

```powershell
F:\anaconda\python.exe .\tools\build_chip_roi_dataset.py existing `
  --output .\chip_roi\generated\existing_pseudo `
  --preview-limit 160 --progress-every 250
```

当前已生成：

```text
chip_roi/generated/existing_pseudo/manifest.csv
chip_roi/generated/existing_pseudo/labels/
chip_roi/generated/existing_pseudo/previews/contact_*.jpg
```

对 MaixCAM 实拍清洁帧生成 `chip` 候选框：

```powershell
F:\anaconda\python.exe .\tools\build_chip_roi_dataset.py captures .\captures `
  --include maixcam `
  --exclude annotated,variants,crop,onnx_diag,contact,preview,smoke,out,top2,confidence,uvc,roi_closed_loop,conf `
  --output .\chip_roi\generated\captures_pseudo `
  --preview-limit 80
```

启动轻量复核 GUI：

```powershell
F:\anaconda\python.exe .\tools\review_chip_roi_labels.py `
  --manifest .\chip_roi\generated\captures_pseudo\manifest.csv
```

GUI 控制只保留最小动作：

- `A/D/W/S`：微调框位置。
- `+/-`：扩缩框，默认每次宽高约变化 `2%`；更细可加 `--scale-step 0.005`。
- `Enter`：接受当前框。
- `Delete`：标为负样本并写空标签。

当前标签格式使用 YOLO detect 的正框 bbox：`class x_center y_center width height`。暂不支持旋转框是为了保持训练、后处理和 ROI 裁剪链路简单稳定；旋转框需要改成 oriented bbox 或分割模型，后续如果要做精细轮廓再单独升级。

## 一体化实拍 GUI

如果是自己实拍并加框，优先使用：

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui
```

这个界面会自动按序保存：

```text
chip_roi/generated/gui_capture/images/chip_0001.jpg
chip_roi/generated/gui_capture/labels/chip_0001.txt
chip_roi/generated/gui_capture/meta/chip_0001.json
chip_roi/generated/gui_capture/previews/chip_0001.jpg
chip_roi/generated/gui_capture/manifest.csv
```

点击 `Capture ROI` 后会自动生成初始 `chip` 框；用 `A/D/W/S`、`+/-` 或界面按钮调框，再用 `Accept`/`Negative` 写入最终状态。

当前 GUI 默认拍摄/预览参数：

```text
Light 50%
Brightness -6
Contrast 1.28
Gamma 0.91
Saturation 0.30
Sharpness 0.85
Denoise 6
```

`Denoise` 在实时预览中使用轻量双边滤波，避免旧的逐帧 NLM 降噪导致拖动滑条时界面卡死。

## 协作复核任务

现有训练集的硬件无关复核任务已拆出 800 张：

```text
chip_roi/review_tasks/existing_pseudo_800/
```

它被拆成 8 个分片，每片 100 张：

```text
part_001 ... part_008
```

成员认领一个分片后运行：

```powershell
F:\anaconda\python.exe .\tools\review_chip_roi_labels.py --manifest .\chip_roi\review_tasks\existing_pseudo_800\part_001\manifest.csv
```

改 `part_001` 为自己认领的分片即可。每个分片独立保存 manifest 和 labels，减少多人协作时的冲突。

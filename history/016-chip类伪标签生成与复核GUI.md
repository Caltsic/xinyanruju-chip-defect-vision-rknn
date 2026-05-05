# chip 类伪标签生成与复核 GUI

更新时间：2026-05-04

## 新增工具

```text
tools/chip_roi_utils.py
tools/build_chip_roi_dataset.py
tools/review_chip_roi_labels.py
```

## 生成现有训练集 chip 伪标签

命令：

```powershell
F:\anaconda\python.exe .\tools\build_chip_roi_dataset.py existing `
  --output .\chip_roi\generated\existing_pseudo `
  --preview-limit 160 --progress-every 250
```

结果：

```text
mode=existing images=2406 output=chip_roi\generated\existing_pseudo
candidate=2406 needs_review=0
manifest=chip_roi\generated\existing_pseudo\manifest.csv
```

输出内容：

```text
chip_roi/generated/existing_pseudo/manifest.csv
chip_roi/generated/existing_pseudo/labels/
chip_roi/generated/existing_pseudo/previews/contact_*.jpg
```

## 生成 MaixCAM 实拍 chip 候选

命令：

```powershell
F:\anaconda\python.exe .\tools\build_chip_roi_dataset.py captures .\captures `
  --include maixcam `
  --exclude annotated,variants,crop,onnx_diag,contact,preview,smoke,out,top2,confidence,uvc,roi_closed_loop,conf `
  --output .\chip_roi\generated\captures_pseudo `
  --preview-limit 80
```

结果：

```text
mode=captures images=8 output=chip_roi\generated\captures_pseudo
candidate=8 needs_review=0
manifest=chip_roi\generated\captures_pseudo\manifest.csv
```

## 复核 GUI

启动命令：

```powershell
F:\anaconda\python.exe .\tools\review_chip_roi_labels.py --manifest .\chip_roi\generated\captures_pseudo\manifest.csv
```

按键：

- `A/D/W/S`：微调框位置。
- `+/-`：扩缩框，默认每次宽高约变化 `2%`；更细可传 `--scale-step 0.005`。
- `Enter`：接受当前框，状态写为 `accepted`。
- `Delete`：写空标签，状态写为 `negative`。
- `Esc` 或 `q`：退出并保存 manifest。

## 注意

- `captures/` 里有大量 annotated、crop、ONNX 诊断、远景和无芯片图，不能无筛选直接当正样本。
- 多芯片场景第一版不追求自动全覆盖；少量样本后续手工补框即可。
- 生成目录位于 `chip_roi/generated/`，已被 `.gitignore` 忽略。
- 预览接触表不要使用黄色细线；白底训练图里不清楚。当前绘制已改为黑色外描边 + 亮紫色内框。
- 当前使用 YOLO detect 正框 bbox，不支持旋转框。原因是第一版目标是稳定裁 ROI，正框训练、NMS、板端后处理和裁剪都更简单；旋转框属于 oriented bbox/分割模型升级项。

## 协作复核任务拆分

- 已从未复核的 `candidate` 中抽取 `800` 张，生成：

```text
chip_roi/review_tasks/existing_pseudo_800/
```

- 拆成 `8` 个分片，每个 `100` 张：

```text
part_001 ... part_008
```

- 每个分片包含独立的 `manifest.csv`、`labels/` 和 `previews/`，图片路径使用仓库相对路径。
- 成员运行示例：

```powershell
F:\anaconda\python.exe .\tools\review_chip_roi_labels.py --manifest .\chip_roi\review_tasks\existing_pseudo_800\part_001\manifest.csv
```

- 该任务不依赖 MaixCAM、IMX415、Astra 或板端硬件。

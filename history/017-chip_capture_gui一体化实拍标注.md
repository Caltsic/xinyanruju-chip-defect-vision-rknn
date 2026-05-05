# chip_capture_gui 一体化实拍标注

更新时间：2026-05-04

## 启动命令

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui
```

## 默认输出

```text
chip_roi/generated/gui_capture/
```

单次采集会输出：

```text
images/chip_0001.jpg
labels/chip_0001.txt
meta/chip_0001.json
previews/chip_0001.jpg
manifest.csv
```

文件名由 GUI 自动按 prefix 和序号生成，默认 prefix 为 `chip`。拍负样本时可以把 prefix 改成 `neg`，但最终训练标签以 `Negative/Delete` 写出的空标签为准。

## 操作流程

1. 点击 `Start` 打开 MaixCAM 实时流。
2. 点击 `Capture ROI` 保存当前帧并自动生成初始 `chip` 框。
3. 用按钮或键盘调框。
4. 点击 `Accept` 或按 `Enter` 接受当前框。
5. 点击 `Negative` 或按 `Delete` 写空标签。

## 调框控制

```text
A/D/W/S  移动当前 chip 框
+/-      扩缩当前 chip 框
Enter    接受当前框
Delete   标为负样本
```

## 设计和工程决策

- 界面已改为绿色二次元主题。
- 第一版仍使用 YOLO detect 正框 bbox，不支持旋转框。
- 自动框复用当前暗区域/边缘 ROI 算法，实拍时使用方形 ROI 和较大 margin。
- 输出目录在 `chip_roi/generated/` 下，默认被 `.gitignore` 忽略。

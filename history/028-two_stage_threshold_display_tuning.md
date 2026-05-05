# 二阶段显示阈值实拍调试

日期：2026-05-05

## 结论

当前二阶段默认观察参数改为：

```text
defect_conf=0.45
defect_confirm=3
display_max_defects=20
```

推荐命令：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

## 限制来源

- `chip` 类：二阶段只选择最高置信度的一颗芯片 ROI，这是当前单芯片定位设计，不是多芯片检测模式。
- defect 类：板端没有“每类最多两个”的限制。原先观感主要来自 PC/GUI 显示端 `display_max_defects` 总量上限和跨类显示 NMS。
- `--display-max-defects 0` 现在表示保留显示 NMS 但不做数量截断。

## 实拍扫描

扫描时关闭 PC 端显示过滤和显示平滑，观察板端时序滤波后的原始输出：

```powershell
--no-display-filter --no-smooth-boxes
```

当前画面结论：

- `0.20-0.35` 召回较多，但会带出更多临界 pinbreak/scratch 候选。
- `0.50` 开始漏掉当前破损芯片上的稳定 broken 候选。
- `0.45 + defect_confirm=3` 较平衡：当前画面中 `chip` 稳定约 `0.90+`，主要 `broken/pinbreak` 稳定框约 `0.5-0.6`。

## 验证

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 120 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20 --save-snapshot .\captures\chip_two_stage_conf045_confirm3_annotated.jpg --save-clean-snapshot .\captures\chip_two_stage_conf045_confirm3_clean.jpg --remote-log /tmp/chip_two_stage_conf045_confirm3.log
```

结果：

```text
Processed frames: 120
末帧 det=5/5
约 8.4 FPS
```

截图：

```text
captures/chip_two_stage_conf045_confirm3_annotated.jpg
captures/chip_two_stage_conf045_confirm3_clean.jpg
```

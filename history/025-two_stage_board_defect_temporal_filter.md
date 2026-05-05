# 二阶段缺陷板端时序滤波

更新时间：2026-05-04

## 背景

二阶段实时链路已经能在一个板端进程里串联 `chip ROI INT8` 和 `defect INT8`，但缺陷框在静态画面中仍会随单帧候选波动跳动，尤其容易在 `pinbreak`、`broken`、`scratch` 之间来回抢同一位置。

本次处理目标不是继续只做 PC 端画框平滑，而是在板端输出 RYL1 检测结果之前先做时序滤波。

## 已实现

- `live_camera_yolo.cc` 新增 `DefectTemporalFilter`，作用在二阶段 defect 结果写入 `cached_defect_results` 之前。
- 每个 defect 轨迹按物理位置做跨类别匹配：
  - IoU 门限：`--defect-match-iou`，默认 `0.10`
  - 中心距离门限：`--defect-match-center`，默认 `0.55`
- 每个 defect 框需要连续命中后才输出：
  - `--defect-confirm`，默认 `2`
- 消失后短时保持，不会一帧 miss 就闪没：
  - `--defect-hold`，默认 `3`
- 框坐标和置信度做 EMA：
  - `--defect-smooth-alpha`，默认 `0.35`
- 类别不再按单帧候选立即切换，而是做衰减投票：
  - `--defect-class-decay`，默认 `0.85`
  - 同一轨迹跨类候选需要明显超过当前类别票数才切换，降低 `pinbreak/broken/scratch` 抢框闪烁。
- `tools/adb_imx415_rknn_live_view.py` 已同步透传上述板端参数。

注意：当前 `defect-confirm` 和 `defect-hold` 按 defect 模型更新计数。默认 `--defect-interval 2` 时，板端会在非 defect 推理帧复用稳定结果，因此不会在复用帧之间闪没。

## 验证

Python 语法检查通过：

```powershell
F:\anaconda\python.exe -m py_compile .\tools\adb_imx415_rknn_live_view.py
```

板端重新编译并安装通过，目标程序：

```text
/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream
```

板端日志确认参数生效：

```text
two_stage=on chip_conf=0.250 defect_conf=0.350 roi_margin=0.080 roi_smooth_alpha=0.350 roi_hold=3 chip_interval=3 defect_interval=2 defect_confirm=2 defect_hold=3 defect_smooth_alpha=0.350 defect_match_iou=0.100 defect_match_center=0.550 defect_class_decay=0.850
```

为验证板端滤波本身，测试时关闭 PC 端平滑和显示过滤：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 160 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --defect-confirm 2 --defect-hold 3 --no-smooth-boxes --no-display-filter --save-snapshot .\captures\chip_two_stage_board_filter_annotated.jpg --save-clean-snapshot .\captures\chip_two_stage_board_filter_clean.jpg --remote-log /tmp/chip_two_stage_board_filter.log
```

结果：

```text
Processed frames: 160
FPS 约 9.5-11.5
```

截图：

```text
captures/chip_two_stage_board_filter_annotated.jpg
captures/chip_two_stage_board_filter_clean.jpg
```

## 当前推荐命令

常规观察：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3
```

更稳但反应稍慢：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --defect-confirm 3 --defect-hold 5 --defect-smooth-alpha 0.25 --display-max-defects 3
```

排查板端原始滤波输出，不叠加 PC 端显示平滑：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --no-smooth-boxes --no-display-filter
```

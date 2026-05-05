# 二阶段实时框稳定化

更新时间：2026-05-04

## 背景

用户反馈 `chip-two-stage-maixcam` 实时窗口中标示框跳动严重，除 `chip` 类外很难稳定观察。当前根因不是 INT8 链路失效，而是三类因素叠加：

- 第一阶段 chip ROI 每帧微小变化会让第二阶段 defect crop 跟着变化。
- defect 模型在当前实拍 ROI 分布下有多个大框低稳定候选。
- 低阈值或 `defect_conf=0.25` 会保留较多重叠/跨类别候选，直接逐帧绘制时观感很跳。

## 本次改动

- 板端 `live_camera_yolo.cc` 新增 chip ROI EMA 平滑：
  - `--roi-smooth-alpha`，默认 `0.35`
  - `--roi-hold`，默认 `3`
  - 该平滑用于二阶段 crop，因此能减少 ROI 抖动传递到 defect 模型。
- PC 端 `tools/adb_imx415_rknn_live_view.py` 新增显示稳定化：
  - `--smooth-boxes` / `--no-smooth-boxes`
  - `--smooth-alpha`，默认 `0.35`
  - `--smooth-hold`，默认 `2`
  - `--smooth-min-hits`，默认 `2`，chip 类首帧仍直接显示
  - `--display-max-defects`，默认 `4`
  - `--display-nms`，默认 `0.30`
  - `--no-display-filter` 查看原始显示输出
- `chip-two-stage-maixcam` 默认开启 PC 显示平滑和显示过滤；其他 profile 默认不受影响。

## 验证

板端已重新编译安装：

```text
/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream
```

60 帧默认平滑验证通过：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 60 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.25 --save-snapshot .\captures\chip_two_stage_smooth_filtered_annotated.jpg --save-clean-snapshot .\captures\chip_two_stage_smooth_filtered_clean.jpg --remote-log /tmp/chip_two_stage_smooth_filtered.log
```

更适合当前画面的观察命令：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3
```

对应 60 帧截图：

```text
captures/chip_two_stage_smooth_conf35_annotated.jpg
captures/chip_two_stage_smooth_conf35_clean.jpg
```

## 结论

- 显示稳定化能改善观察体验，但不能把 defect 模型的大框误检变成精细定位。
- 当前若想观察真实破损处，建议先用 `defect_conf=0.35` 和 `--display-max-defects 3`；需要诊断召回时再降到 `0.25` 或 `0.05`。
- 后续要从根上稳定 defect 框，需要继续补 ROI 内实拍训练数据，并针对 `broken/pinbreak/scratch` 标签尺度和框大小做重训或精修。

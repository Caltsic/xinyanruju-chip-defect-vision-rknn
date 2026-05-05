# 二阶段 FPS 节奏优化

更新时间：2026-05-04

## 背景

用户反馈二阶段实时流约 `7 FPS`，观感接近 PPT。澄清后确认之前提到的 `60 帧` 是 `--frames 60` 稳定性测试帧数，不是 `60 FPS`。

## 基线测试

同一 MaixCAM 1280x720 MJPG 输入、headless 观察：

```text
chip-roi-maixcam 单模型：约 9.6-10.3 FPS
chip-defect-maixcam 单模型：约 9.4-10.0 FPS
chip-two-stage-maixcam 原每帧双模型：约 6.5-7.0 FPS
```

结论：瓶颈主要是每帧连续跑 chip ROI INT8 和 defect INT8 两次 NPU，不是 PC 端预览参数。

## 本次改动

板端 `live_camera_yolo.cc` 新增推理节奏控制：

```text
--chip-interval N
--defect-interval N
```

PC 端 `tools/adb_imx415_rknn_live_view.py` 同步暴露参数，并在二阶段 profile 中传给板端。

默认值：

```text
chip-interval=3
defect-interval=2
```

含义：

- chip ROI 每 3 帧重新定位一次，其余帧复用平滑 ROI。
- defect 每 2 帧重新推理一次，其余帧复用上一组 defect 框。
- 视频帧仍每帧回传，检测框更新频率降低但画面明显更顺。

## 验证结果

默认优化节奏：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 160 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3
```

结果：约 `10.3-10.9 FPS`。

速度优先静态场景：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --frames 160 --headless --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3 --chip-interval 5 --defect-interval 3
```

结果：约 `11.3-12.4 FPS`。

## 取舍

- `chip-interval 3 / defect-interval 2` 是默认平衡档，适合正常观察。
- `chip-interval 5 / defect-interval 3` 是速度优先档，适合芯片基本静止、只需要更流畅画面时。
- 若需要逐帧检测输出用于严肃诊断，可显式使用：

```powershell
--chip-interval 1 --defect-interval 1
```

这会回到约 `7 FPS` 的每帧双模型路径。

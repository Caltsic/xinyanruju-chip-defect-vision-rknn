# 调焦曝光颜色闪烁与 rkaiq_3A 诊断

更新时间：2026-04-28

## 关键结论

- IMX415 基础链路已打通，问题不在摄像头未识别。
- 当前画面有效，但曾出现明显模糊、噪声、颜色/亮度闪烁。
- 现象更像物理焦距、自动曝光、自动白平衡、IQ/3A 收敛问题。
- `/dev/video42` 是正确 ISP 输出，后续调试基于它。

## 3A 与占用情况

- `rkaiq_3A_server` 正在运行。
- `/dev/video11` 和 `/dev/v4l-subdev7` 被 `rkaiq_3A_server` 占用，属于正常 3A/ISP 工作现象。
- 直接通过 `v4l2-ctl` 写 sensor 曝光/增益会被 `rkaiq_3A_server` 覆盖。
- `rkisp_demo --gain/--expo` 理论上支持手动 AE，但一次临时停止 3A 后的手动采帧试验超时，已恢复 3A，不继续冒险使用这条路。

## 控制项发现

IMX415 子设备 `/dev/v4l-subdev7` 可见控制：

- `exposure`
- `horizontal_flip`
- `vertical_flip`
- `vertical_blanking`
- `horizontal_blanking`
- `analogue_gain`
- `link_frequency`
- `pixel_rate`

未看到标准 V4L2 白平衡或防频闪控制项。

## IQ 文件与 3A 配置

已确认 IMX415 IQ 文件存在：

- `/etc/iqfiles/imx415_CMK-OT2022-PX1_IR0147-36IRC-8M-F20.json`
- `/etc/iqfiles/imx415_CMK-OT2022-PX1_IR0147-50IRC-8M-F20.json`

日志显示 `rkaiq_3A_server` 加载：

- `/etc/iqfiles//imx415_CMK-OT2022-PX1_IR0147-50IRC-8M-F20.json`

IQ 文件中已见：

- `antiFlicker` 已启用。
- 频率为 `ae_antiFlicker_50hz_freq`。
- 白平衡 `wbGainCtrl` 默认为 `RK_AIQ_OP_MODE_AUTO`，存在手动参数 `manual_wbgain`。

## 亮度/颜色闪烁原因判断

- 开流后前若干帧亮度明显爬升，是 3A 启动收敛导致。
- 日志可见 `imx415` 在流启动时持续设置 exposure 和 analog gain。
- ADB raw 预览反复开停流会触发 3A 反复启动/停止，从而放大闪烁感。
- 近距离、高反光、过曝场景会让 AE/AWB 更容易抖动。

## 传输与分辨率发现

- 3840x2160 NV12 原始帧太大，不适合直接通过 ADB raw 做实时预览。
- 1280x720 raw 也可能吞吐不稳，曾出现短帧或 ISP stop timeout。
- 640x360 稳定但画面偏暗/比例不理想。
- 640x480 可出现过曝。
- 960x540 当前较稳，画面正常，适合作为默认电脑端预览分辨率。
- 脚本默认分辨率已改为 `960x540`，默认丢弃 8 帧 warmup。

## 调焦辅助

脚本支持：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_yolo_preview.py --no-detect --diagnostics
```

指标含义：

- `focus`：Laplacian 方差，通常越大越清晰。
- `Y`：灰度亮度均值。
- `std`：亮度标准差。
- `BGR`：颜色通道均值。
- `delta`：帧间平均差异，越大代表画面变化或闪烁越明显。

物理调焦建议：

1. 对准 0.5m 到 2m 外的高纹理物体。
2. 缓慢旋转镜头。
3. 观察 `focus` 达到局部最大且稳定。
4. 避免画面大面积白色或强反光，否则 AE/AWB 会不稳定。

## 当前建议

- 不要先改 IQ 文件，先通过诊断预览完成物理调焦。
- 调焦时保持环境光稳定，避免频繁开停脚本。
- 如颜色继续闪，再考虑基于 IQ 文件把 AWB/AE 改为手动或降低 AE 收敛敏感度。
- RKNN/NPU 迁移应在画面稳定后继续，否则模型输出会被画质问题干扰。


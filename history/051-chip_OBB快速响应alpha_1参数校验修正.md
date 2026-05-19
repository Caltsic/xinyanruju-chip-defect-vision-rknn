# Chip OBB 快速响应 alpha=1 参数校验修正

Updated: 2026-05-09

## Summary

本归档记录快速响应命令中 `--roi-smooth-alpha 1.0` 被 PC 端和板端参数解析拒绝的问题、修复范围、编译部署过程和验证结果。

不记录 SSH 密码、端口、token、IP 凭据或其他敏感凭据。

## Symptom

用户运行快速响应命令时，PC 端 argparse 报错：

```text
--roi-smooth-alpha: must be between 0 and 1
```

原因是原 `threshold_float` 使用：

```text
0.0 < x < 1.0
```

但对 EMA 平滑参数来说，`alpha=1.0` 是合理的“立即跟随”语义，不应该被拒绝。

后续发现板端二进制自己的参数解析也拒绝 `1.0`，日志为：

```text
invalid value for --roi-smooth-alpha: 1.0; expected 0.0 < value < 1.0
```

## PC Fix

修复文件：

```text
tools/adb_imx415_rknn_live_view.py
```

新增：

```text
smoothing_alpha_float
```

校验范围改为：

```text
0.0 < alpha <= 1.0
```

以下参数改用 `smoothing_alpha_float`：

```text
--roi-smooth-alpha
--defect-smooth-alpha
--smooth-alpha
```

置信度、NMS、ROI margin 等 threshold 参数仍保持 strict threshold，不放宽到 `1.0`。

## Board Fix

修复文件：

```text
rknn_work/board_yolo11_src/examples/yolo11/cpp/live_camera_yolo.cc
```

新增：

```text
parse_alpha_option
```

校验范围改为：

```text
0.0 < value <= 1.0
```

以下参数改用 `parse_alpha_option`：

```text
--roi-smooth-alpha
--defect-smooth-alpha
--defect-class-decay
```

其他 threshold 参数不放宽。

## Build Notes

板端源码与构建目录：

```text
/tmp/rknn_yolo11_src
/tmp/rknn_yolo11_build
```

第一次编译失败，原因是 `isfinite` 未加 `std::` 命名空间。

修正为：

```text
std::isfinite
```

之后编译成功：

```text
make -C /tmp/rknn_yolo11_build -j2 rknn_chip_two_stage_maixcam_stream
```

## Deployment

部署前备份板端旧二进制：

```text
/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream.bak_pre_alpha_1_20260509
```

新二进制复制到：

```text
/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream
```

## Verification

验证命令：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-obb-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20 --chip-interval 1 --roi-smooth-alpha 1.0 --roi-hold 0 --frames 8 --headless --remote-log /tmp/obb_fast_alpha_check.log
```

结果：

```text
Processed frames 8
det=1/1
```

## Follow-Up Notes

- `alpha=1.0` 只表示 EMA 立即跟随，不等同于置信度、NMS、ROI margin 等阈值参数的满值语义。
- 后续新增 smoothing/decay 类参数时，应使用 alpha 专用解析函数，而不是复用 strict threshold 解析函数。

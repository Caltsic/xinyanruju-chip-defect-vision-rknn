# 电脑端 OpenCV 预览与 YOLO ONNX 识别脚本

更新时间：2026-04-28

## 目标

在 Windows 电脑端实时查看泰山派3M-RK3576 上 IMX415 摄像头画面，并用本地 YOLO ONNX 模型做常见物品识别 demo。

## 关键链路

- 板端摄像头入口：`/dev/video42`
- 板端输出格式：NV12
- 传输：ADB `exec-out` 拉流到 Windows
- 显示：Windows 端 OpenCV
- 推理：Windows 端 `onnxruntime` CPU
- 当前不是板端 NPU/RKNN 推理。

## 新增或修改文件

- 预览与识别脚本：
  - `F:\WORKSPACE\泰山派\tools\adb_imx415_yolo_preview.py`
- README 已追加运行说明：
  - `F:\WORKSPACE\泰山派\README.md`

## Windows 依赖环境

- Python：`F:\anaconda\python.exe`
- OpenCV：`cv2 4.13.0`
- NumPy：可用
- ONNX Runtime：`1.24.4`
- Provider：`CPUExecutionProvider`

当前 demo 不依赖：

- `torch`
- `ultralytics`

## 使用模型

优先使用：

`F:\WORKSPACE\泰山派\立创·泰山派3开发板资料\8.【立创·泰山派3】Ai应用\YOLO11\yolo11n.onnx`

已知模型信息：

- 输入：`images: float32 [1, 3, 640, 640]`
- 该模型可被 `onnxruntime` 加载。

不推荐当前使用：

- `YOLOv8\yolov8n.onnx`
- 原因：缺少外部权重 `yolov8n.onnx.data`，不是完整单文件 ONNX。

## 运行命令

PowerShell：

```powershell
cd F:\WORKSPACE\泰山派
F:\anaconda\python.exe .\tools\adb_imx415_yolo_preview.py
```

只看实时画面、不跑识别：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_yolo_preview.py --no-detect
```

调焦/稳定度辅助：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_yolo_preview.py --no-detect --diagnostics
```

无窗口保存截图：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_yolo_preview.py --no-detect --headless --frames 1 --save-snapshot .\captures\preview_smoke.jpg
```

退出窗口：

- `q`
- `Esc`

## 验证结果

已验证纯预览截图：

- `F:\WORKSPACE\泰山派\captures\preview_smoke.jpg`

已验证 YOLO demo 截图：

- `F:\WORKSPACE\泰山派\captures\yolo_preview_smoke.jpg`

当时曾启动实时识别窗口，进程号 `25724`；该 PID 只代表当时状态，后续不能假设仍在运行。

## 脚本当前特性

- 默认使用 `/dev/video42`，不使用 `/dev/video0` 或 `/dev/video51`。
- 从板端读取 NV12，在 Windows 转 BGR。
- 支持 `--no-detect` 排除推理开销。
- 支持 `--headless`、`--frames`、`--save-snapshot`。
- 支持 `--diagnostics` 显示 focus、亮度、BGR 均值、帧间 delta。
- 支持 `--metrics-csv` 输出每帧诊断数据。
- 已加入远端 `v4l2-ctl` 清理逻辑，降低窗口退出后残留占用的概率。
- 默认分辨率已调整为 `960x540`，并默认丢弃开流前 8 帧以避开 3A 启动收敛闪烁。

## 当前已知问题

- ADB raw 拉 4K 或 1280x720 原始 NV12 时吞吐不稳，可能出现短帧或 ISP stop timeout。
- 960x540 在当前环境下更稳，适合预览和调焦。
- 当前画面质量仍依赖物理调焦和 3A/IQ 稳定性。
- 当前 YOLO 在 Windows CPU 上跑，不代表 RK3576 NPU 性能。

## 后续建议

1. 先用 `--no-detect --diagnostics` 调清焦距和观察亮度稳定性。
2. 再运行 YOLO ONNX demo，把 COCO 常见物体放入画面。
3. 画面稳定后再推进 RKNN/NPU 迁移。


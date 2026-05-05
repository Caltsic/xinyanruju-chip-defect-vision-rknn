# chip ROI 实时部署归档与下一阶段入口

更新日期：2026-05-04

## 当前可用状态

- MaixCAM Pro 已作为 UVC 摄像头接入泰山派 3M，节点为 `/dev/video73`。
- UVC 有效格式为 `MJPG 1280x720 @ 30fps`；实时链路仍需容忍 MJPEG 偶发坏帧和 `/dev/video73` 单路占用。
- 板端已安装 chip ROI 一类实时二进制：
  - `/userdata/rknn_yolo11_demo/rknn_chip_roi_camera_stream`
  - `/userdata/rknn_yolo11_demo/rknn_chip_roi_maixcam_stream`
- 板端已安装 chip ROI 模型与标签：
  - `/userdata/rknn_yolo11_demo/model/chip_roi_yolov8_detect_fp.rknn`
  - `/userdata/rknn_yolo11_demo/model/chip_roi_yolov8_detect_int8.rknn`
  - `/userdata/rknn_yolo11_demo/model/chip_roi_labels.txt`
- PC 端 `chip-roi-maixcam` profile 当前默认加载 FP RKNN，只作为已验证可出框的诊断/临时基线；面向 RK3576 NPU 的正确主线仍是 INT8。

## 当前命令

chip-only 实时框：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-roi-maixcam --conf 0.25
```

启动 `chip-*` profile 时，脚本会自动先下发：

```text
WS2812 rgb=190,255,100 brightness=0.50
```

PC 端实时窗口和 annotated snapshot 默认套用：

```text
Brightness -6
Contrast 1.28
Gamma 0.91
Saturation 0.30
Sharpness 0.85
Denoise 6
```

`--save-clean-snapshot` 仍保存原始 clean 帧；上述图像参数只影响 PC 端显示/截图，不改变板端 NPU 输入。

## 已验证结果

- `chip_roi_yolov8_detect_fp.rknn`：
  - `--profile chip-roi-maixcam --conf 0.25 --frames 5 --headless` 可出 `det=1/1`。
  - 自动补光/预览预设后，`--frames 10 --headless` 可出 `det=3/3`。
- `chip_roi_yolov8_detect_int8.rknn`：
  - 能加载，输出形状为 `1x5x8400`。
  - 当前 MaixCAM 画面下 `conf=0.25` 和 `conf=0.05` 均无框。
  - 判断为 INT8 量化或输出反量化尺度问题，应优先修复。
- PC 侧 ONNX 对同一类 clean 帧可定位 chip ROI，说明训练出的 chip 模型路线成立。

## 当前产物

关键截图：

```text
captures/chip_roi_maixcam_profile_default_annotated.jpg
captures/chip_roi_maixcam_profile_default_clean.jpg
captures/chip_roi_maixcam_auto_setup10_annotated.jpg
captures/chip_roi_maixcam_auto_setup10_clean.jpg
captures/chip_roi_maixcam_onnx_check/
```

关键代码入口：

```text
tools/adb_imx415_rknn_live_view.py
tools/roi_defect_closed_loop.py
rknn_work/board_yolo11_src/examples/yolo11/cpp/live_camera_yolo.cc
rknn_work/board_yolo11_src/examples/yolo11/cpp/postprocess.cc
rknn_work/board_yolo11_src/examples/yolo11/cpp/CMakeLists.txt
```

## 下一阶段

优先级 1：chip ROI INT8 修复。

- 在板端后处理里增加可开关的 top score/raw output 统计，比较 FP16 和 INT8 的最大 chip score、xywh 范围和反量化值。
- 用同一帧 clean image 做 ONNX、FP RKNN、INT8 RKNN 对照。
- 判断根因：
  - 后处理反量化/阈值问题：直接修 C++。
  - RKNN 转换/校准问题：重新转换 INT8。
- 成功标准：`chip_roi_yolov8_detect_int8.rknn` 在 MaixCAM 当前画面 `conf=0.25` 或合理阈值下稳定输出 chip 框。

优先级 2：INT8 两阶段实时闭环。

```text
MaixCAM frame
  -> chip ROI INT8 RKNN on full frame
  -> select/expand chip box
  -> defect INT8 RKNN on chip crop
  -> map defect boxes back
  -> RYL1 packet returns chip + defect boxes
```

建议新增 profile：

```text
chip-two-stage-maixcam
```

建议显示类别：

```text
chip, ZF-scratch, scratch, broken, pinbreak
```

优先级 3：把预览预处理迁入板端推理输入。

- 当前 `Brightness/Contrast/Gamma/Saturation/Sharpness/Denoise` 只影响 PC 显示。
- 若实验证明预处理能提升缺陷/字符/引脚模型置信度，再把轻量版本迁入 C++，并避免让补光/色彩调整造成训练分布漂移。

## 风险

- `/dev/video73` 是单路占用，短时间连续启动可能遇到 `Device or resource busy`；通常等待上一进程释放或用更长 `--frames` 复测即可。
- 两阶段板端融合不能继续依赖编译期单一 `OBJ_CLASS_NUM`；需要把 YOLOv8 single-output 后处理改成可按模型输出通道数或运行时 class count 工作。
- FP RKNN 可用于诊断和临时回退，但不应作为当前硬件上的最终默认路径。

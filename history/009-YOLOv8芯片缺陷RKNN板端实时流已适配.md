# YOLOv8 芯片缺陷 RKNN 板端实时流已适配

更新时间：2026-05-02

## 目标

把云端训练得到的 YOLOv8 芯片缺陷检测模型部署到泰山派 3M RK3576，基于 IMX415 `/dev/video42` 实时采集，在板端 NPU 推理，并通过 ADB 二进制流回传到电脑端 OpenCV 实时显示。

## 已部署文件

板端目录仍复用：

```text
/userdata/rknn_yolo11_demo
```

新增或更新的关键文件：

```text
/userdata/rknn_yolo11_demo/rknn_chip_defect_camera_stream
/userdata/rknn_yolo11_demo/model/chipcheck_yolov8_detect_int8.rknn
/userdata/rknn_yolo11_demo/model/chipcheck_yolov8_detect_fp.rknn
/userdata/rknn_yolo11_demo/model/chip_defect_labels.txt
```

旧 YOLO11 程序和 COCO 模型仍保留，可继续用 `--profile yolo11` 验证。

## 关键适配

- `postprocess.h` 支持编译期覆盖 `OBJ_CLASS_NUM`、`BOX_THRESH`、`NMS_THRESH`。
- `postprocess.cc` 支持编译期覆盖标签文件路径。
- 新增 `rknn_chip_defect_camera_stream` CMake 目标：
  - `OBJ_CLASS_NUM=4`
  - 默认模型：`model/chipcheck_yolov8_detect_int8.rknn`
  - 默认标签：`./model/chip_defect_labels.txt`
- 补充 YOLOv8 单输出后处理：
  - RKNN 输出数量：`1`
  - 输出形状：`1 x 8 x 8400`
  - 通道含义：`cx, cy, w, h, ZF-scratch, scratch, broken, pinbreak`
  - 后处理流程：单输出解码 -> letterbox 反变换 -> class-wise NMS -> RYL1 协议回传。
- `tools/adb_imx415_rknn_live_view.py` 默认 profile 改为 `chip-defect`，并保留 `--profile yolo11`。

## 板端验证结果

板端 1 帧自检命令返回 `RET=0`，INT8 模型信息：

```text
input:  images, dims=[1, 640, 640, 3], type=INT8
output: output0, dims=[1, 8, 8400], type=INT8
```

电脑端 INT8 冒烟：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --frames 3 --headless --save-snapshot .\captures\chip_defect_live_int8_smoke.jpg
```

结果：

```text
Processed frames: 3
Saved snapshot: captures\chip_defect_live_int8_smoke.jpg
```

电脑端 FP 冒烟：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --remote-model model/chipcheck_yolov8_detect_fp.rknn --frames 3 --headless --save-snapshot .\captures\chip_defect_live_fp_smoke.jpg
```

结果：

```text
Processed frames: 3
Saved snapshot: captures\chip_defect_live_fp_smoke.jpg
```

当前摄像头画面未放置芯片目标，冒烟结果 `det=0` 合理。

## 使用命令

实时窗口：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py
```

调低阈值观察候选框：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --conf 0.15
```

FP 基线对比：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --remote-model model/chipcheck_yolov8_detect_fp.rknn
```

YOLO11 旧链路：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile yolo11
```

窗口中按 `q` 或 `Esc` 退出。

## 调焦状态

已检查板端 V4L2 控制项：

- `/dev/video42` 只有 `pixel_rate`。
- `/dev/v4l-subdev7` 只有 `exposure`、翻转、blanking、`analogue_gain`、`link_frequency`、`pixel_rate`。
- media 拓扑只看到 `m00_b_imx415 5-0037`，没有 VCM/lens/focus 实体。

因此当前模组不能软件自动调焦，只能手动旋转镜头。`tools/adb_imx415_rknn_live_view.py` 已在状态栏加入 `focus` 清晰度评分，按拉普拉斯方差计算；调焦时让该数值达到局部最大即可。

## 注意事项

- INT8 RKNN 的输出是单个 INT8 tensor，量化 scale 受坐标通道影响较大；真实芯片画面上应继续做 INT8 与 FP 的同帧对比。
- 若真实芯片画面检出过少，优先尝试 `--conf 0.15` 或 FP 模型排查，不先改训练流程。
- 若真实芯片画面误检过多，再提高 `--conf` 或补充负样本重新量化。

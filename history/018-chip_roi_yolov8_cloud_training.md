# chip ROI YOLOv8 Cloud Training

更新时间：2026-05-04

## 目标

训练第一版一类 `chip` 定位模型，用于把 MaixCAM/Astra/IMX415 全图先裁成芯片 ROI，再交给现有四类缺陷模型做二阶段检测。

## 输入数据

- 协作复核任务：`chip_roi/review_tasks/existing_pseudo_800/`
  - `accepted=754`
  - `negative=46`
- GUI 实拍采集：`chip_roi/generated/gui_capture/`
  - manifest 有效纳入 `accepted=375`
  - manifest 有效纳入 `negative=3`
  - 有两条 manifest 记录对应图片缺失，未纳入训练包：`chip_0288.jpg`、`chip_0313.jpg`
- 打包后训练数据：`chip_roi/generated/cloud_chip_roi_yolo/`
  - 总图片 `1178`
  - chip 框 `1129`
  - 空标签负样本 `49`
  - train/valid/test：`964/111/103`

负样本按原图分组后基底不足 10 组，因此第一版全部放入训练集，避免增强图泄漏到验证/测试集。后续若要评估误检率，需要补一批真实无芯片负样本并单独分到 valid/test。

## 本地训练包

构建脚本：

```powershell
F:\anaconda\python.exe .\tools\build_chip_roi_cloud_package.py --overwrite
```

输出：

```text
cloud_training/chip_roi_yolov8_rknn_cloud_package.zip
chip_roi/generated/cloud_chip_roi_yolo/cloud_package_report.json
chip_roi/generated/cloud_chip_roi_yolo/dataset_report.json
```

本地校验命令：

```powershell
F:\anaconda\python.exe .\cloud_training\chip_roi_yolov8_rknn\scripts\prepare_dataset.py `
  --raw-dataset .\chip_roi\generated\cloud_chip_roi_yolo `
  --output-dir .\chip_roi\generated\cloud_chip_roi_yolo_check `
  --calib-output .\chip_roi\generated\cloud_chip_roi_yolo_check\calib_dataset.txt `
  --labels-output .\chip_roi\generated\cloud_chip_roi_yolo_check\chip_roi_labels.txt `
  --overwrite --image-mode copy
```

校验结果：

```text
Images: 1178, objects: 1129
train: images=964, labels=964, objects=915, empty_labels=49
valid: images=111, labels=111, objects=111, empty_labels=0
test: images=103, labels=103, objects=103, empty_labels=0
```

## 云端执行策略

云机环境：

```text
Ubuntu 22.04
Python 3.12.3
PyTorch 2.8.0+cu128
GPU: NVIDIA GeForce RTX 5090
```

依赖顺序很重要：先安装训练依赖并训练/导出 ONNX，再安装 RKNN-Toolkit2 做 RKNN 转换。RKNN-Toolkit2 可能安装自己的依赖集合，提前安装会增加破坏 PyTorch/CUDA 训练环境的风险。

远端工作目录：

```text
/root/autodl-tmp/chip_roi_train_20260504/
```

云端流水线：

```bash
cd /root/autodl-tmp/chip_roi_train_20260504/chip_roi_yolov8_rknn
python -m pip install --upgrade pip wheel
python -m pip install "setuptools==69.5.1"
python -m pip install -r requirements.txt

python scripts/run_all.py \
  --raw-dataset dataset_raw/chip_roi_yolo \
  --work-dir outputs \
  --model yolov8n.pt \
  --imgsz 640 \
  --epochs 200 \
  --batch 64 \
  --device 0 \
  --workers 8 \
  --patience 50 \
  --calib-count 300 \
  --target-platform rk3576 \
  --overwrite-dataset \
  --skip-rknn

python scripts/install_rknn_toolkit2.py --third-party-dir third_party
python scripts/convert_rknn.py \
  --onnx outputs/final/chip_roi_yolov8_detect.onnx \
  --output-dir outputs/final/rknn \
  --calib-dataset outputs/calib_dataset.txt \
  --target-platform rk3576 \
  --name chip_roi_yolov8_detect
```

## 预期产物

需要从云端拉回并本地保存：

```text
outputs/final/chip_roi_yolov8_detect.pt
outputs/final/chip_roi_yolov8_detect.onnx
outputs/final/chip_roi_yolov8_detect_fp.rknn
outputs/final/chip_roi_yolov8_detect_int8.rknn
outputs/final/chip_roi_labels.txt
outputs/final/calib_dataset.txt
outputs/final/dataset_report.json
outputs/final/rknn/rknn_conversion_report.json
outputs/final/artifact_manifest.json
cloud_run.log
```

板端优先部署 `chip_roi_yolov8_detect_int8.rknn`，保留 FP RKNN 和 ONNX 作为排查基线。

## 实际执行记录

- 云端自动下载 `yolov8n.pt` 曾出现 303 KB 半截文件，训练初始化停滞。已改为从本地上传已知可用的 `yolov8n.pt` 到：

```text
/root/autodl-tmp/chip_roi_train_20260504/yolov8n.pt
```

- 实际训练使用固定 `batch=64`，比 `batch=-1` 自动探测更可控。
- 训练完成 200 epoch，用时约 `0.145 h`，最佳验证结果来自 epoch `183`：

```text
precision=0.99946
recall=1.00000
mAP50=0.99500
mAP50-95=0.93583
```

- Rockchip `ultralytics_yolov8` 导出 ONNX 成功，输出形状为 `(1, 5, 8400)`。`onnxslim` 缺失导致 simplify 跳过，但 ONNX 导出成功。
- 直接 `git clone https://github.com/airockchip/rknn-toolkit2.git` 在云机上卡住，已改用 PyPI 镜像安装：

```bash
python -m venv ../rknn_env
../rknn_env/bin/python -m pip install "rknn-toolkit2==2.3.2" -i https://pypi.tuna.tsinghua.edu.cn/simple
../rknn_env/bin/python -m pip install "onnx==1.16.1" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

- `rknn-toolkit2==2.3.2` 与 `onnx==1.21.0` 不兼容，报错 `module 'onnx' has no attribute 'mapping'`。固定 `onnx==1.16.1` 后 FP/INT8 RKNN 均转换成功。

## 本地已拉回产物

```text
cloud_training/chip_roi_outputs_20260504/
```

关键文件：

```text
outputs/final/chip_roi_yolov8_detect.pt
outputs/final/chip_roi_yolov8_detect.onnx
outputs/final/chip_roi_yolov8_detect_fp.rknn
outputs/final/chip_roi_yolov8_detect_int8.rknn
outputs/final/rknn/rknn_conversion_report.json
outputs/final/artifact_manifest.json
outputs/train/chip_roi_yolov8_detect/results.csv
logs/cloud_run_v2.log
logs/rknn_convert_v2_failed_onnx21.log
logs/rknn_convert_v3.log
```

文件大小：

```text
PT:        6,255,530 bytes
ONNX:     12,237,969 bytes
FP RKNN:  13,132,021 bytes
INT8 RKNN:10,198,351 bytes
```

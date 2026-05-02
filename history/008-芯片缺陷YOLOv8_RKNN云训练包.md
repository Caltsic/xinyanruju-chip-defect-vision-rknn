# 芯片缺陷 YOLOv8 RKNN 云训练包

更新时间：2026-05-02

## 目标

为半导体芯片表面缺陷数据集建立云端训练与转换包，产出可用于 RK3576 NPU 部署的 YOLOv8 检测模型。

第一版目标：

- 只做检测框，不做分割掩膜。
- 使用 YOLOv8 detect。
- 同时导出 FP RKNN 和 INT8 RKNN。
- INT8 作为板端主部署模型，FP 作为排障基准。

## 数据集结论

数据集路径：

`半导体芯片表面缺陷检测/半导体芯片表面缺陷检测-解压后可直接使用/半导体芯片表面缺陷检测`

实际可读数据：

- train：2138 图 / 2138 标注
- valid：133 图 / 133 标注
- test：135 图 / 135 标注
- total：2406 图 / 2406 标注
- 图片分辨率：全部 `2592x1944`

类别：

- `0 ZF-scratch`
- `1 scratch`
- `2 broken`
- `3 pinbreak`

标签格式不是纯 detection bbox，实际为混合格式：

- 原始 train、valid、test 多数为 YOLO polygon segmentation。
- train 中 `_aug_0` 样本为 YOLO bbox。
- 因此检测训练前必须先生成独立 bbox 数据副本，不能直接拿原始 labels 训练 detect。

## 新增文件

云训练包源码：

- `cloud_training/yolov8_rknn/README.md`
- `cloud_training/yolov8_rknn/BOARD_DEPLOYMENT_NOTES.md`
- `cloud_training/yolov8_rknn/scripts/prepare_dataset.py`
- `cloud_training/yolov8_rknn/scripts/train_yolov8.py`
- `cloud_training/yolov8_rknn/scripts/export_onnx.py`
- `cloud_training/yolov8_rknn/scripts/convert_rknn.py`
- `cloud_training/yolov8_rknn/scripts/run_all.py`
- `cloud_training/yolov8_rknn/scripts/install_rknn_toolkit2.py`

项目工具：

- `tools/build_chip_defect_cloud_package.py`

规划文件：

- `plans/chip_defect_yolov8_rknn_cloud_package_plan.md`

## 云端流程

云端包内默认数据集路径：

`dataset_raw/chip_defect_raw`

推荐命令：

```bash
cd chipcheck_yolov8_rknn
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python scripts/install_rknn_toolkit2.py --third-party-dir third_party
python scripts/run_all.py --raw-dataset dataset_raw/chip_defect_raw --work-dir outputs --model yolov8n.pt --imgsz 640 --epochs 150 --device 0
```

最终产物目录：

`outputs/final`

核心产物：

- `chipcheck_yolov8_detect.pt`
- `chipcheck_yolov8_detect.onnx`
- `chipcheck_yolov8_detect_fp.rknn`
- `chipcheck_yolov8_detect_int8.rknn`
- `chip_defect_labels.txt`
- `calib_dataset.txt`
- `dataset_report.json`

## 板端注意事项

当前项目已跑通的实时程序是 YOLO11：

`/userdata/rknn_yolo11_demo/rknn_yolo11_camera_stream`

它的后处理硬编码 COCO 80 类，并绑定 YOLO11/Rockchip 分头 DFL 输出结构，不能直接替换为 YOLOv8 缺陷模型。

YOLOv8 上板时最短路线：

1. 使用 Rockchip `rknn_model_zoo/examples/yolov8` C++ demo 作为后处理基线。
2. 修改类别数为 4，替换 label 为 `chip_defect_labels.txt`。
3. 替换模型为 `chipcheck_yolov8_detect_int8.rknn`。
4. 再把现有 `/dev/video42`、NV12、ADB `RYL1` 实时流逻辑移植到 YOLOv8 demo。

## 官方依据

- `https://github.com/airockchip/rknn_model_zoo`
- `https://github.com/airockchip/ultralytics_yolov8`
- `https://github.com/airockchip/rknn-toolkit2`
- `https://wiki.lckfb.com/en/tspi-3-rk3576/ai/yolov8/detection-model.html`

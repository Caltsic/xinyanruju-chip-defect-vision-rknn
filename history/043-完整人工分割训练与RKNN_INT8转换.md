# 完整人工分割训练与 RKNN INT8 转换
Updated: 2026-05-07

## Background

本轮目标是把局域网 CVAT 已完成的全部人工分割标注合并为完整训练集，使用云端 RTX 5090 重新训练 YOLOv8s-Seg，并完成 RK3576 可用的 RKNN INT8 转换。

纳入训练的 CVAT exports：

- `chipCheck_1.zip`
- `chipCheck_2.zip`
- `chipCheck_4.zip`
- `chipCheck_9.zip`
- `chipCheck_12.zip`
- `task_15_dataset_2026_05_07_07_58_02_coco 1.0.zip`
- `task_16_dataset_2026_05_07_07_30_06_coco 1.0.zip`
- `task_17_dataset_2026_05_07_07_22_57_coco 1.0.zip`
- `task_18_dataset_2026_05_07_09_26_13_coco 1.0.zip`
- `task_19_dataset_2026_05_07_03_33_54_coco 1.0.zip`
- `task_20_dataset_2026_05_07_06_51_05_coco 1.0.zip`
- `task_21_dataset_2026_05_07_07_39_08_coco 1.0.zip`

明确排除：

- `chipCheck_test.zip`

排除原因：该包 annotations 为 0，且与早期样本存在重复；如果混入训练，会把同一图像同时作为有缺陷标注和空标注样本，污染监督信号。它更适合做单独测试或留作负样本复核，不应并入本轮监督训练。

## Dataset Merge

本地合并数据集：

```text
cloud_training/yolov8_seg_rknn/dataset_raw/imx678_seg_full_manual_20260507/
```

合并时必须按 `category name` 映射类别，不能按 COCO `category_id` 直接转换。原因是早期 `chipCheck_2/4/9/12` 和后续 task15-21 的 `scratch` / `pinbreak` category id 顺序不同。

合并统计：

- images: `1700`
- COCO annotations: `5548`
- written polygon objects: `5544`
- skipped annotations: `4`
- empty images: `357`
- classes: `ZF-scratch`, `scratch`, `broken`, `pinbreak`

split 统计：

| split | images | objects | empty images |
| --- | ---: | ---: | ---: |
| train | 1445 | 4758 | 296 |
| valid | 170 | 497 | 42 |
| test | 85 | 289 | 19 |
| total | 1700 | 5544 | 357 |

关键报告：

```text
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/dataset_raw/imx678_seg_full_manual_20260507/merge_report.json
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/dataset_report.json
```

## Cloud Runtime

云端 SSH：

```bash
ssh -p 50897 root@connect.westd.seetacloud.com
```

密码未写入本归档。

云端工作目录：

```bash
/root/autodl-tmp/chipcheck_seg_full_manual_20260507
```

使用 `/root/autodl-tmp` 的原因：`/root` overlay 可用空间小，训练数据、pip 缓存、ONNX、RKNN 和日志都应放在数据盘目录，避免系统盘爆满。

Python：

```bash
/root/miniconda3/bin/python
```

GPU：RTX 5090。

## Cloud Fixes

本轮云端环境遇到并处理了以下问题：

1. 坏的 `ultralytics` editable install

   云端 `ultralytics==8.2.82` 元数据存在，但实际是 editable install，指向已经不存在的路径，导致 `import ultralytics` 失败。处理方式是卸载后重新从正常 wheel 安装固定版本。

2. 缺少 `onnxscript` / `onnx_ir`

   ONNX 导出链路需要补齐相关依赖。补装后继续导出。

3. `pip` 卡住

   依赖安装过程中出现 pip 卡住，后续采用更小范围、分步安装/修复，避免长时间卡在一次性安装过程。

4. `numpy 2.4.4` 缺 `np.trapz`

   训练中途失败过一次，原因是当前依赖组合下 `numpy 2.4.4` 不再提供 `np.trapz`，触发 Ultralytics 指标计算异常。处理方式是降级/固定 numpy 到兼容版本后重新训练。

5. `onnx 1.21` 与 `rknn-toolkit2` 的 `onnx.mapping` 兼容问题

   RKNN 转换阶段遇到 `onnx.mapping` 兼容问题。处理方式是调整 ONNX 依赖版本，使 `rknn-toolkit2 2.3.2` 可以正常 build FP 和 INT8 RKNN。

相关日志：

```text
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/logs/minimal_install_20260507.log
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/logs/numpy_fix_20260507.log
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/logs/onnx_fix_20260507.log
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/logs/train_full_manual_20260507.failed_numpy_180624.log
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/logs/train_full_manual_20260507.log
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/logs/rknn_full_manual_20260507.log
```

## Training Command

训练入口使用：

```bash
cd /root/autodl-tmp/chipcheck_seg_full_manual_20260507/cloud_training/yolov8_seg_rknn

/root/miniconda3/bin/python scripts/run_all.py \
  --raw-dataset dataset_raw/imx678_seg_full_manual_20260507 \
  --work-dir outputs_full_manual_20260507 \
  --model yolov8s-seg.pt \
  --name chipcheck_yolov8s_seg_full_manual_20260507 \
  --imgsz 640 \
  --epochs 200 \
  --batch -1 \
  --device 0 \
  --workers 8 \
  --patience 60 \
  --seed 42 \
  --calib-count 300 \
  --class-count 4 \
  --mask-count 32 \
  --overwrite-dataset \
  --keep-empty-images
```

说明：本轮要求生成 INT8，因此没有使用 `--skip-rknn`。最终导出和转换都落在 `outputs_full_manual_20260507/final/`。

## Training Result

训练早停于 epoch `143`。

最佳权重对应 epoch `76`，关键指标：

- `metrics/mAP50(M)`: `0.93841`
- `metrics/mAP50-95(M)`: `0.57255`
- `metrics/mAP50(B)`: `0.97306`
- `metrics/mAP50-95(B)`: `0.69203`
- `metrics/precision(M)`: `0.93775`
- `metrics/recall(M)`: `0.91187`

训练结果 CSV：

```text
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/train/chipcheck_yolov8s_seg_full_manual_20260507/results.csv
```

## ONNX And RKNN

ONNX 导出记录：

```text
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/chipcheck_yolov8s_seg_full_manual_20260507.export_report.json
```

导出报告显示：

- `task`: `segment`
- `imgsz`: `640`
- `opset`: `12`
- `exporter`: `standard_ultralytics_fallback`
- Rockchip ultralytics fork 不存在，因此使用 standard Ultralytics fallback 导出。

注意：ONNX fallback/opset 转换存在告警，但没有阻塞 RKNN 转换。RKNN 转换最终成功，`rknn_conversion_report.json` 显示使用的是 split ONNX：

```text
using_split_onnx: true
onnx_used: /root/autodl-tmp/chipcheck_seg_full_manual_20260507/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/chipcheck_yolov8s_seg_full_manual_20260507_split.onnx
target_platform: rk3576
rknn_toolkit2: 2.3.2
```

RKNN 报告：

```text
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/rknn/rknn_conversion_report.json
```

## Final Artifacts

本地结果包：

```text
cloud_training/yolov8_seg_outputs_full_manual_20260507/chipcheck_seg_full_manual_20260507_results.zip
```

大小：`208,395,645 bytes`

本地解压目录：

```text
cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/
```

最终产物：

| artifact | local path | size |
| --- | --- | ---: |
| PT weights | `cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/chipcheck_yolov8s_seg_full_manual_20260507.pt` | 23,870,644 bytes |
| ONNX | `cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/chipcheck_yolov8s_seg_full_manual_20260507.onnx` | 47,626,011 bytes |
| ONNX data | `cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/chipcheck_yolov8s_seg_full_manual_20260507.onnx.data` | 47,251,456 bytes |
| split ONNX | `cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/chipcheck_yolov8s_seg_full_manual_20260507_split.onnx` | 47,626,610 bytes |
| FP RKNN | `cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/chipcheck_yolov8s_seg_full_manual_20260507_fp.rknn` | 31,693,423 bytes |
| INT8 split RKNN | `cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/chipcheck_yolov8s_seg_full_manual_20260507_split_int8.rknn` | 19,657,136 bytes |
| Labels | `cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/chip_defect_seg_labels.txt` | 35 bytes |
| Calibration list | `cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/calib_dataset.txt` | 78,500 bytes |

远端最终目录：

```bash
/root/autodl-tmp/chipcheck_seg_full_manual_20260507/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/
```

远端 RKNN 输出：

```bash
/root/autodl-tmp/chipcheck_seg_full_manual_20260507/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/rknn/chipcheck_yolov8s_seg_full_manual_20260507_fp.rknn
/root/autodl-tmp/chipcheck_seg_full_manual_20260507/cloud_training/yolov8_seg_rknn/outputs_full_manual_20260507/final/rknn/chipcheck_yolov8s_seg_full_manual_20260507_split_int8.rknn
```

## Board Deployment Notes

后续板端部署优先使用：

```text
chipcheck_yolov8s_seg_full_manual_20260507_split_int8.rknn
```

FP RKNN 保留为排查基线：

```text
chipcheck_yolov8s_seg_full_manual_20260507_fp.rknn
```

部署注意：

- 本轮 INT8 是目标产物，板端应部署 split INT8，而不是原始 ONNX 或 FP RKNN。
- RKNN INT8 转换可能出现输入/输出 dtype 相关 warning；这类 warning 不等价于转换失败，但上板后必须做单帧和实时流 smoke test。
- 若 INT8 上板后出现类别错乱、mask 偏移、mask 全空、输出 shape 不匹配，先用 FP RKNN 同输入对比，再检查 split 输出顺序是否仍为 `boxes / scores / mask_coeffs / protos`。
- `chip_defect_seg_labels.txt` 和后处理类别顺序必须保持：`ZF-scratch`, `scratch`, `broken`, `pinbreak`。
- 上板后应重点确认 ROI 裁剪、mask 解码、时序滤波、mask-only 显示和标签显示是否仍与上一版运行时兼容。

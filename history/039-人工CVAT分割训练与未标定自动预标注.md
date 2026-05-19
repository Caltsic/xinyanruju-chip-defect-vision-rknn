# 人工CVAT分割训练与未标定自动预标注

日期：2026-05-06

## 背景

用户已完成以下 CVAT 分割标注并导出到：

`chip_seg/cavt_export/`

- `chipCheck_test`（Task1）
- `chipCheck_1`
- `chipCheck_2`
- `chipCheck_4`
- `chipCheck_9`
- `chipCheck_12`

本轮目标是：先用已完成的人工 CVAT 分割标注训练一版 YOLOv8-Seg，再对 `gui_session_20260506_163553` 中尚未人工标定的图片生成缺陷分割预标注，减少后续人工修改量。

## 归档关联文件

- 规划文件：`plans/seg_cvat_train_autolabel_20260506.md`
- 本地人工合并数据集：`cloud_training/yolov8_seg_rknn/dataset_raw/imx678_seg_manual_20260506/`
- 未标定工作目录：`chip_seg/work/manual_20260506/`
- 云端回拉结果：`cloud_training/yolov8_seg_outputs_manual_20260506/`
- 自动预标注 session：`chip_seg/captures/gui_session_20260506_163553_auto_manual_v1_unlabeled/`
- 自动预标注 CVAT 包：`chip_seg/cvat_tasks/gui_session_20260506_163553_auto_manual_v1_unlabeled_150/`

## CVAT export 审核结果

已审核 `chip_seg/cavt_export/` 中的 6 个 zip：

| Export | 图像数 | 标注数 | 备注 |
| --- | ---: | ---: | --- |
| `chipCheck_1.zip` | 147 | 675 | 使用 `annotations/instances_default.json`，图像在 `images/default` |
| `chipCheck_2.zip` | 143 | 178 | 使用 `annotations/instances_Train.json`，图像在 `images/Train` |
| `chipCheck_4.zip` | 147 | 604 | 人工标定完成 |
| `chipCheck_9.zip` | 149 | 670 | 人工标定完成 |
| `chipCheck_12.zip` | 150 | 86 | 人工标定完成 |
| `chipCheck_test.zip` | 37 | 0 | 与早期样本重复，且 0 标注，未纳入训练 |

类别包含四类缺陷：

- `ZF-scratch`
- `scratch`
- `broken`
- `pinbreak`

注意：各 zip 内 COCO category id 顺序不完全一致，合并脚本按类别名映射，避免了 id 顺序差异带来的错类风险。

## 排除 chipCheck_test 的原因

`chipCheck_test.zip` 包含 37 张早期图片，和 `chipCheck_1.zip` 的早期样本 stem 有重叠，并且自身 annotations 为 0。

如果把它和 `chipCheck_1.zip` 一起合入训练，会形成“同图有缺陷标注”和“同图空标注”的矛盾样本，因此本轮训练明确排除 `chipCheck_test.zip`。

## 合并训练集统计

合并命令：

```powershell
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py merge-coco --inputs .\chip_seg\cavt_export\chipCheck_1.zip .\chip_seg\cavt_export\chipCheck_2.zip .\chip_seg\cavt_export\chipCheck_4.zip .\chip_seg\cavt_export\chipCheck_9.zip .\chip_seg\cavt_export\chipCheck_12.zip --output-dir .\cloud_training\yolov8_seg_rknn\dataset_raw\imx678_seg_manual_20260506 --splits 0.85,0.1,0.05 --overwrite
```

输出数据集：

`cloud_training/yolov8_seg_rknn/dataset_raw/imx678_seg_manual_20260506/`

统计：

| split | 图像数 | polygon objects | empty images |
| --- | ---: | ---: | ---: |
| train | 626 | 1858 | 154 |
| valid | 74 | 248 | 14 |
| test | 36 | 103 | 8 |
| total | 736 | 2209 | 176 |

覆盖统计文件：

`chip_seg/work/manual_20260506/coverage_report.json`

关键结果：

- 完整采集 session：`chip_seg/captures/gui_session_20260506_163553`
- 全量图片：1761
- 人工 export 覆盖唯一 stem：736
- 未人工标定 stem：1025
- 未标定列表：`chip_seg/work/manual_20260506/unlabeled_stems.txt`
- 未标定图片副本：`chip_seg/work/manual_20260506/unlabeled_images/`

未标定 stem 主要范围：

`seg_0065`, `seg_0074`, `seg_0078`, `seg_0172`, `seg_0229-seg_0231`, `seg_0246`, `seg_0252`, `seg_0272`, `seg_0301-seg_0450`, `seg_0589`, `seg_0592`, `seg_0594`, `seg_0601-seg_1091`, `seg_1227`, `seg_1242-seg_1541`, `seg_1692-seg_1761`。

## 云端环境与工作目录

云端 SSH：

```bash
ssh -p 41081 root@connect.westd.seetacloud.com
```

密码属于临时敏感信息，未写入本归档。

云端工作目录：

```bash
/root/autodl-tmp/chipcheck_seg_manual_20260506
```

选择 `/root/autodl-tmp` 的原因：

- `/root` overlay 空间较小；
- `/root/autodl-tmp` 可用空间约 50GB，更适合训练和数据包展开。

上传包：

```text
chip_seg/work/manual_20260506/chipcheck_seg_manual_20260506_cloud.zip
```

云端包路径：

```bash
/root/autodl-tmp/chipcheck_seg_manual_20260506/chipcheck_seg_manual_20260506_cloud.zip
```

包内包含：

- `cloud_training/yolov8_seg_rknn/` 的训练脚本、配置、依赖和数据集；
- `tools/split_yolov8_seg_onnx_outputs.py`
- `tools/yolo_seg_predict_labels.py`
- `metadata/unlabeled_stems.txt`
- `metadata/coverage_report.json`
- `unlabeled_images/` 中的 1025 张未标定图。

## Ultralytics 修复

云端 Python：

```bash
/root/miniconda3/bin/python
```

云端原有 `ultralytics` 是坏的 editable 安装，`pip` 显示已安装，但 `import ultralytics` 失败，原因是 editable 指向了不存在路径：

```text
/root/autodl-tmp/chipcheck_yolov8_rknn/outputs/third_party/ultralytics_yolov8
```

处理：

```bash
/root/miniconda3/bin/python -m pip uninstall -y ultralytics
/root/miniconda3/bin/python -m pip install --no-cache-dir "ultralytics==8.2.82" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

验证结果：

```text
IMPORT_OK 8.2.82 /root/miniconda3/lib/python3.12/site-packages/ultralytics/__init__.py
```

## 权重下载慢的处理

初次训练启动后卡在从 GitHub 下载：

```text
https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8s-seg.pt
```

下载进度很慢，训练尚未进入 epoch。

处理方式：

- 本地使用已有网络下载 `yolov8s-seg.pt`；
- 保存到 `cloud_training/yolov8s-seg.pt`；
- 上传到云端训练目录，避免云端继续慢速 GitHub 下载；
- 同时上传本地 `cloud_training/yolov8n.pt`，用于规避 Ultralytics AMP check 触发额外下载延迟。

本地权重文件：

- `cloud_training/yolov8s-seg.pt`
- `cloud_training/yolov8n.pt`

## 训练命令

云端训练命令：

```bash
cd /root/autodl-tmp/chipcheck_seg_manual_20260506/cloud_training/yolov8_seg_rknn
/root/miniconda3/bin/python scripts/run_all.py \
  --raw-dataset dataset_raw/imx678_seg_manual_20260506 \
  --work-dir outputs_manual_20260506 \
  --model yolov8s-seg.pt \
  --name chipcheck_yolov8s_seg_manual_20260506 \
  --imgsz 640 \
  --epochs 120 \
  --batch -1 \
  --device 0 \
  --workers 8 \
  --patience 25 \
  --seed 42 \
  --calib-count 300 \
  --overwrite-dataset \
  --keep-empty-images \
  --skip-rknn \
  --no-auto-clone-rockchip-exporter \
  --no-install-rockchip-exporter \
  --standard-export-fallback
```

训练日志：

```bash
/root/autodl-tmp/chipcheck_seg_manual_20260506/logs/train_manual_20260506.log
```

本轮目的只是离线预标注，不要求立即 RKNN 转换，所以使用 `--skip-rknn`。后续要上板部署时再做 RKNN 转换和板端验证。

## 训练结果

训练完成 120 epochs。

最终模型云端路径：

```bash
/root/autodl-tmp/chipcheck_seg_manual_20260506/cloud_training/yolov8_seg_rknn/outputs_manual_20260506/final/chipcheck_yolov8s_seg_manual_20260506.pt
```

本地回拉后的模型路径：

```text
cloud_training/yolov8_seg_outputs_manual_20260506/extracted/cloud_training/yolov8_seg_rknn/outputs_manual_20260506/final/chipcheck_yolov8s_seg_manual_20260506.pt
```

训练 `results.csv`：

```text
cloud_training/yolov8_seg_outputs_manual_20260506/extracted/cloud_training/yolov8_seg_rknn/outputs_manual_20260506/train/chipcheck_yolov8s_seg_manual_20260506/results.csv
```

epoch 120 关键指标：

- `metrics/mAP50(B)`：约 0.972
- `metrics/mAP50-95(B)`：约 0.628
- `metrics/mAP50(M)`：约 0.967
- `metrics/mAP50-95(M)`：约 0.527
- `val/box_loss`：约 1.459
- `val/seg_loss`：约 2.246

这些指标只作为相对 sanity check。当前数据集仍较小且类别/场景不均衡，CVAT 人工复核仍是事实来源。

## ONNX 失败但不阻塞

本轮云端 ONNX export 失败，原因是云端缺少 `onnxscript`。

该失败不阻塞当前目标，因为：

- 当前目标是对未标定图片离线生成预标注；
- 预标注使用 `.pt` 在 RTX 5090 上推理即可；
- RKNN/ONNX 转换属于后续板端部署阶段。

后续若要继续转 RKNN，应先在云端补齐 `onnxscript`，再检查 `onnx`、`rknn-toolkit2`、torch 版本兼容性。

## 自动预标注推理

云端推理使用最终 `.pt` 模型，对 1025 张未人工标定图片生成 YOLO-seg label。

推理参数：

- `imgsz=640`
- `conf=0.20`
- `iou=0.50`
- `max_det=20`
- `device=0`

输出目录：

```bash
/root/autodl-tmp/chipcheck_seg_manual_20260506/auto_labels_manual_20260506_conf020
```

首次直接对完整目录推理出现两个问题：

1. `Too many open files`
2. CUDA OOM

原因：Ultralytics 对 list source / 大目录推理时会一次性装载过多图片或保持过多文件句柄。

处理：使用同一模型、同一阈值参数分块推理，最终完成 1025 张图的 label 生成。

最终统计：

- label txt：1025
- 非空 txt：593
- 空 txt：432
- 总预测对象：1751

预测日志：

```text
cloud_training/yolov8_seg_outputs_manual_20260506/extracted/logs/predict_manual_20260506_conf020.log
```

## 结果包与拉回路径

云端结果包：

```bash
/root/autodl-tmp/chipcheck_seg_manual_20260506/manual_20260506_results.zip
```

大小：

```text
22,993,826 bytes
```

本地结果包：

```text
cloud_training/yolov8_seg_outputs_manual_20260506/manual_20260506_results.zip
```

本地解压目录：

```text
cloud_training/yolov8_seg_outputs_manual_20260506/extracted/
```

压缩包包含：

- final `.pt` 模型目录；
- `results.csv`；
- `auto_labels_manual_20260506_conf020/`；
- `metadata/unlabeled_stems.txt`；
- `metadata/coverage_report.json`；
- `logs/predict_manual_20260506_conf020.log`。

远端执行过 `unzip -t` 完整性检查，通过。

## 本地自动预标注 session

本地生成的自动预标注 session：

```text
chip_seg/captures/gui_session_20260506_163553_auto_manual_v1_unlabeled/
```

生成报告：

```text
chip_seg/captures/gui_session_20260506_163553_auto_manual_v1_unlabeled/auto_prelabel_report.json
```

报告结果：

```json
{
  "saved": 1025,
  "requested": 1025,
  "missing": [],
  "missing_count": 0
}
```

该 session 包含：

- `images/`：1025 张 ROI 图；
- `labels/`：1025 个 YOLO-seg label；
- `images_full/`：对应原始全图；
- `previews/`：预标注预览图；
- `meta/`：元数据；
- `manifest.csv`：CVAT 打包和追踪用清单。

原始人工采集 session 没有被覆盖。

## CVAT part 包

CVAT-ready 包目录：

```text
chip_seg/cvat_tasks/gui_session_20260506_163553_auto_manual_v1_unlabeled_150/
```

分包统计：

| part | 图像数 | annotations | zip |
| --- | ---: | ---: | --- |
| `part_001` | 150 | 160 | `part_001.zip` |
| `part_002` | 150 | 643 | `part_002.zip` |
| `part_003` | 150 | 327 | `part_003.zip` |
| `part_004` | 150 | 223 | `part_004.zip` |
| `part_005` | 150 | 325 | `part_005.zip` |
| `part_006` | 150 | 40 | `part_006.zip` |
| `part_007` | 125 | 33 | `part_007.zip` |

合计：

- 图像：1025
- annotations：1751
- zip 包：7

每个 `part_*.zip` 可作为 CVAT Task 导入。若要多人并行标注，建议每个 part 建一个 Task；如果全部放一个 Task，也可以用 CVAT Job 分配，但任务权限、进度隔离和导出管理会更弱。

## 新增/修复脚本

新增：

`tools/yolo_seg_predict_labels.py`

用途：使用 Ultralytics segmentation `.pt` 模型对图片目录生成 YOLO-seg `.txt` 标签。

关键参数：

- `--weights`
- `--source`
- `--output-labels`
- `--imgsz`
- `--conf`
- `--iou`
- `--max-det`
- `--device`
- `--chunk-size`

修复点：

- 增加 `--chunk-size`；
- 将输入图片按 chunk 调用 Ultralytics，避免一次性完整目录推理造成 `Too many open files` 或 CUDA OOM；
- 输出空预测也会写空 `.txt`，保证 label 数和图片数一致。

新增：

`tools/build_auto_prelabel_session.py`

用途：把预测得到的 YOLO-seg label 还原为本项目 GUI capture session 结构，保留原 ROI、全图、预览、meta 和 manifest，便于继续 `package-cvat`。

修复点：

- 在脚本开头加入项目根目录到 `sys.path`；
- 解决直接运行脚本时 `from tools.seg_cvat_pipeline import ...` 的导入路径问题；
- 不覆盖原始采集 session，而是写入新的 `*_auto_manual_v1_unlabeled` 目录。

验证：

```powershell
F:\anaconda\python.exe -m py_compile .\tools\yolo_seg_predict_labels.py .\tools\build_auto_prelabel_session.py .\tools\seg_cvat_pipeline.py
```

通过。

## 后续使用建议

1. 在 CVAT 中导入 `chip_seg/cvat_tasks/gui_session_20260506_163553_auto_manual_v1_unlabeled_150/part_001.zip` 到 `part_007.zip`。
2. 这些包是“未人工标定部分”的自动预标注，不要和已经人工完成的 `chipCheck_1/2/4/9/12` 重复标。
3. 标注员重点做三件事：
   - 删除误检 mask；
   - 调整边界不准确的 mask；
   - 补上漏检缺陷。
4. 空标注图片不一定真无缺陷，仍要快速扫一遍。
5. `conf=0.20` 是偏召回的预标注阈值，误检会多一些，但更适合“人工删改”流程。
6. 后续所有新人工修正完成后，再导出 CVAT dataset，合并为下一轮训练集；届时应把这 1025 张中的人工修正结果作为真值，而不是保留本轮 auto label。
7. 如果要把该模型上板，先补 ONNX export 依赖，再做 RKNN 转换、板端 smoke test 和实时窗口稳定性验证。


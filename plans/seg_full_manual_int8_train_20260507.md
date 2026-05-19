# Seg Full Manual INT8 Training Plan 2026-05-07

## Goal

Use all completed manual CVAT segmentation exports to train the next chip defect YOLOv8-seg model on the RTX 5090 cloud host, then export ONNX and RKNN INT8 artifacts for RK3576 board deployment.

## Inputs

- CVAT exports: `chip_seg/cavt_export/`
- New remaining tasks: `task_15` through `task_21`
- Previous manually completed tasks: `chipCheck_1`, `chipCheck_2`, `chipCheck_4`, `chipCheck_9`, `chipCheck_12`
- Excluded previous duplicate empty task: `chipCheck_test`
- Cloud host: `ssh -p 50897 root@connect.westd.seetacloud.com`
- Training package: `cloud_training/yolov8_seg_rknn`

## Planned Outputs

- Full manual YOLO-seg dataset:
  - `cloud_training/yolov8_seg_rknn/dataset_raw/imx678_seg_full_manual_20260507`
- Cloud work directory:
  - `/root/autodl-tmp/chipcheck_seg_full_manual_20260507`
- Local pulled artifacts:
  - `cloud_training/yolov8_seg_outputs_full_manual_20260507/`
- Expected final artifacts:
  - `.pt`
  - `.onnx`
  - split `.onnx`
  - FP `.rknn`
  - split INT8 `.rknn`
  - calibration dataset and RKNN conversion report

## Phases

1. [complete] Audit task15-21 CVAT exports and determine safe training inputs.
2. [complete] Merge all completed manual exports into a full YOLO-seg dataset.
3. [complete] Package and upload code, dataset, and local weights to the cloud host.
4. [complete] Fix/verify cloud Python dependencies for Ultralytics, ONNX export, and RKNN Toolkit2.
5. [complete] Train YOLOv8-seg on RTX 5090.
6. [complete] Export ONNX, split ONNX, and RKNN FP/INT8.
7. [complete] Pull artifacts back locally and verify counts/metrics/files.
8. [in_progress] Archive results into `history/`.

## Decisions

- Train from the complete human-verified dataset, not only task15-21, unless audit reveals duplicate contradictory exports.
- Keep `chipCheck_test.zip` excluded because it duplicates early stems and has zero annotations.
- Use `yolov8s-seg.pt` as the first complete manual model unless cloud/RKNN constraints force a smaller fallback.
- Do not overwrite previous `outputs_manual_20260506` artifacts.
- Use INT8 RKNN with representative calibration images generated from the full manual training set.

## Open Checks

- Exact file names and annotation counts for task15-21.
- task15-21 contain no duplicate stems versus the previously included `chipCheck_1/2/4/9/12`.
- The new cloud image has `rknn-toolkit2==2.3.2` but broken editable `ultralytics`, missing `onnxscript`, and `/root` only has about 3.5GB free. Use `/root/autodl-tmp`.
- Use a two-stage cloud run: training/ONNX/split first, then RKNN FP/INT8 conversion after pinning a RKNN-compatible ONNX stack.

## Current Stats

- Included CVAT exports: `chipCheck_1`, `chipCheck_2`, `chipCheck_4`, `chipCheck_9`, `chipCheck_12`, `task_15` through `task_21`.
- Excluded: `chipCheck_test` because it duplicates early stems and has zero annotations.
- Full merged dataset: 1700 images, 5544 written polygon objects, 357 empty negative images.
- Split:
  - train: 1445 images, 4758 objects, 296 empty images
  - valid: 170 images, 497 objects, 42 empty images
  - test: 85 images, 289 objects, 19 empty images

## Results

- Cloud work directory: `/root/autodl-tmp/chipcheck_seg_full_manual_20260507`
- Local result package: `cloud_training/yolov8_seg_outputs_full_manual_20260507/chipcheck_seg_full_manual_20260507_results.zip`
- Local extracted artifacts: `cloud_training/yolov8_seg_outputs_full_manual_20260507/extracted/`
- Training ran 143 epochs and stopped early by patience. The stable final `.pt` is copied from best weights.
- Best validation by mask mAP50-95:
  - epoch: 76
  - box mAP50: 0.97306
  - box mAP50-95: 0.69203
  - mask mAP50: 0.93841
  - mask mAP50-95: 0.57255
- Last logged epoch 143:
  - box mAP50: 0.97014
  - box mAP50-95: 0.70147
  - mask mAP50: 0.93830
  - mask mAP50-95: 0.55188
- Exported artifacts:
  - `chipcheck_yolov8s_seg_full_manual_20260507.pt` 23,870,644 bytes
  - `chipcheck_yolov8s_seg_full_manual_20260507.onnx` 47,626,011 bytes
  - `chipcheck_yolov8s_seg_full_manual_20260507.onnx.data` 47,251,456 bytes
  - `chipcheck_yolov8s_seg_full_manual_20260507_split.onnx` 47,626,610 bytes
  - `chipcheck_yolov8s_seg_full_manual_20260507_fp.rknn` 31,693,423 bytes
  - `chipcheck_yolov8s_seg_full_manual_20260507_split_int8.rknn` 19,657,136 bytes
- Dependency notes:
  - Broken editable `ultralytics` was fixed by installing `ultralytics==8.2.82`.
  - A stuck `pip --force-reinstall` briefly upgraded `numpy` to 2.4.4, breaking `np.trapz`; fixed with `numpy==1.26.4`.
  - RKNN Toolkit2 failed with `onnx 1.21.0` because `onnx.mapping` is absent; fixed with `onnx==1.16.1`.
  - ONNX export used standard Ultralytics fallback, not Rockchip fork. Opset conversion to 12 failed for `Resize`, so the exported model kept a newer opset, but RKNN conversion from split ONNX succeeded.

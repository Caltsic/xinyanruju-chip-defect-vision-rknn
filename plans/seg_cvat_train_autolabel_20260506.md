# Seg CVAT Training + Auto-Relabel Plan 2026-05-06

## Goal

Use the completed CVAT manual segmentation exports to train one improved YOLOv8-seg model on the RTX 5090 cloud host, then use that model to regenerate defect segmentation prelabels for captured images that have not yet been manually annotated.

## Inputs

- CVAT exports: `chip_seg/cavt_export/`
- Full captured GUI session: `chip_seg/captures/gui_session_20260506_163553/`
- Previously packaged ranges:
  - `seg_0001` to `seg_0791`
  - `seg_0792` to `seg_1761`
- Cloud host: `ssh -p 41081 root@connect.westd.seetacloud.com`
- Training package: `cloud_training/yolov8_seg_rknn`

## Planned Outputs

- Merged manual YOLO-seg dataset:
  - `cloud_training/yolov8_seg_rknn/dataset_raw/imx678_seg_manual_20260506`
- Cloud work directory:
  - `/root/autodl-tmp/chipcheck_seg_manual_20260506`
- Local trained artifacts:
  - `cloud_training/yolov8_seg_outputs_manual_20260506/`
- Auto-prelabel dataset for not-yet-manual images:
  - `chip_seg/captures/gui_session_20260506_163553_auto_manual_v1_unlabeled/`
- CVAT packages for the new auto-prelabels:
  - `chip_seg/cvat_tasks/gui_session_20260506_163553_auto_manual_v1_unlabeled_150/`

## Phases

1. [complete] Audit CVAT exports and determine which image stems are manually annotated.
2. [complete] Merge CVAT COCO exports into YOLO-seg training dataset and validate class/object statistics.
3. [complete] Determine unlabeled stems by subtracting manual stems from the full captured set.
4. [complete] Package and upload training code + merged dataset to the cloud host.
5. [complete] Train YOLOv8-seg on RTX 5090, export artifacts, and pull results back locally.
6. [complete] Run cloud inference with the new model on unlabeled images to create improved YOLO-seg prelabels.
7. [complete] Package auto-prelabels into CVAT-ready 150-image zip tasks.
8. [complete] Archive results into `history/`.

## Decisions

- Treat only images present in the completed CVAT exports as human-verified.
- Do not overwrite original GUI-captured labels; write regenerated prelabels to a new session directory.
- Prefer training first with `--skip-rknn`; RKNN conversion/deployment is not required for offline relabeling, but artifacts should still be suitable for later conversion.
- Use `paramiko` for remote SSH/SFTP because password auth is required and interactive SSH would block automation.

## Open Checks

- Verify whether exported CVAT zips include images (`Save images` enabled).
- Verify task exports map back to source stems such as `seg_0001`.
- Verify cloud Python/CUDA/ultralytics availability before launching full training.
- If the cloud image lacks RKNN/ONNX dependencies, train/predict with `.pt` first and postpone RKNN conversion.

## Errors / Notes

- User path is intentionally `chip_seg/cavt_export` (typo-like name), not `cvat_export`.
- `chipCheck_test.zip` overlaps early stems already covered by `chipCheck_1.zip` and contains 37 images with 0 annotations. It is excluded from the first training dataset to avoid contradictory duplicate labels.
- Training dataset `imx678_seg_manual_20260506` created from `chipCheck_1/2/4/9/12` with `--splits 0.85,0.1,0.05`: train 626 images / 1858 objects / 154 empty, valid 74 / 248 / 14 empty, test 36 / 103 / 8 empty.
- Full capture session has 1761 images; manual export stems cover 736 unique images; unlabeled list has 1025 stems and is saved in `chip_seg/work/manual_20260506/unlabeled_stems.txt`.
- Cloud `ultralytics` was a broken editable install; fixed by reinstalling `ultralytics==8.2.82`.
- Cloud GitHub download of `yolov8s-seg.pt` was too slow. Downloaded locally to `cloud_training/yolov8s-seg.pt`, uploaded to the cloud, and restarted training. Also uploaded local `yolov8n.pt` to avoid AMP check download delay.
- Training completed 120 epochs on RTX 5090. Final model was pulled through `cloud_training/yolov8_seg_outputs_manual_20260506/manual_20260506_results.zip`.
- Final validation at epoch 120: box mAP50 about 0.972, mask mAP50 about 0.967, mask mAP50-95 about 0.527. Use these as relative sanity metrics only; CVAT review remains the source of truth.
- ONNX export failed on the cloud because `onnxscript` was missing. This did not block the current auto-prelabel phase because `.pt` inference was used.
- Cloud prelabel inference on 1025 unlabeled images produced 1025 txt files, 593 non-empty images, 432 empty images, and 1751 predicted objects at `conf=0.20`.
- Local auto-prelabel session created at `chip_seg/captures/gui_session_20260506_163553_auto_manual_v1_unlabeled`.
- CVAT packages created at `chip_seg/cvat_tasks/gui_session_20260506_163553_auto_manual_v1_unlabeled_150`: `part_001.zip` to `part_007.zip`, with 150/150/150/150/150/150/125 images and 160/643/327/223/325/40/33 annotations.

# YOLOv8-Seg Board Smoke Test

## Date

2026-05-05

## Facts

- New defect segmentation model deployed to the board:
  - `/userdata/rknn_yolo11_demo/model/chipcheck_yolov8_seg_split_int8.rknn`
  - `/userdata/rknn_yolo11_demo/model/chipcheck_yolov8_seg_fp.rknn`
- The board's old `rknn_chip_two_stage_maixcam_stream` did not support `--defect-model-kind`; the first smoke test exited with `unknown argument: --defect-model-kind`.
- Rebuilt `rknn_chip_two_stage_maixcam_stream` natively on the RK3576 board from local `rknn_work/board_yolo11_src` and replaced the board binary.
- Previous board binary was kept as:
  - `/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream.bak_pre_seg_20260505`
- New binary help confirms support for:
  - `--defect-model-kind detect|seg`
  - `--stream-contours|--no-stream-contours`
  - `--seg-sidecar PATH`

## Smoke Result

Command profile:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.30 --defect-confirm 1 --display-max-defects 20 --frames 10 --headless --save-snapshot .\captures\seg_board_smoke_annotated.jpg --save-clean-snapshot .\captures\seg_board_smoke_clean.jpg
```

Result:

- Exit code: `0`
- Processed frames: `10`
- Last frame status: `FPS 8.7 | focus 159 | 1280x720 | det 2/2 | frame 9`
- Board log confirmed split seg outputs:
  - `boxes`
  - `scores`
  - `mask_coeffs`
  - `protos`
- Screenshot showed `chip 0.98` and `scratch 0.56`; scratch had an orange contour/mask overlay.
- Output screenshots:
  - `captures/seg_board_smoke_annotated.jpg`
  - `captures/seg_board_smoke_clean.jpg`

## Notes

- RKNN output tensors are INT8 and must continue to use RKNN scale/zero-point dequantization in postprocess.
- Board log still prints `src width is not 4/16-aligned, convert image use cpu`; this is a performance warning, not a functional failure.

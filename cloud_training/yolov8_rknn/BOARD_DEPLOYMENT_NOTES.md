# RK3576 Board Deployment Notes

This cloud package produces YOLOv8 detection RKNN models. The current repository already has a working YOLO11 live camera stream, but that binary is not a drop-in runtime for YOLOv8 outputs.

## Required Board-Side Work

Use Rockchip `rknn_model_zoo/examples/yolov8` as the board-side baseline, then apply the project camera stream work already proven in the YOLO11 demo:

1. Build or port `rknn_yolov8_demo` for `rk3576_linux_aarch64`.
2. Replace `coco_80_labels_list.txt` with `chip_defect_labels.txt`.
3. Set class count to `4` in the YOLOv8 postprocess, or make it configurable from the label file.
4. Replace the demo model with `chipcheck_yolov8_detect_int8.rknn` for deployment.
5. Keep `chipcheck_yolov8_detect_fp.rknn` on the board for debugging and FP-vs-INT8 comparison.
6. Reuse the existing IMX415 capture path:
   - device: `/dev/video42`
   - pixel format: `NV12`
   - default live stream: `960x540`
   - input letterbox to model size: `640x640`

## Do Not

- Do not feed this YOLOv8 RKNN into the current `rknn_yolo11_camera_stream` without changing postprocess.
- Do not keep `OBJ_CLASS_NUM=80`; it must be `4`.
- Do not keep COCO label files in the chip defect deployment directory.
- Do not deploy INT8 without checking it against FP on the same images.

## Acceptance Check

The board-side smoke test should prove:

- RKNN Runtime loads the INT8 model on RK3576.
- Inference uses NPU and does not fall back to a CPU-only path.
- The live view displays only these labels: `ZF-scratch`, `scratch`, `broken`, `pinbreak`.
- FP and INT8 predictions are close enough on the same chip test frames.

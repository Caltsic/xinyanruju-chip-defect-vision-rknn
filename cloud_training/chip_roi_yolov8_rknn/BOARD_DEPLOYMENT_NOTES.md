# Board Deployment Notes

This package produces a YOLOv8 RKNN model for one-class chip ROI detection.
It is not the four-class defect model.

## Runtime Integration

- Target model: `chip_roi_yolov8_detect_int8.rknn`
- Debug model: `chip_roi_yolov8_detect_fp.rknn`
- Class count: `1`
- Label file: `chip_roi_labels.txt`
- Class name: `chip`

Use the existing YOLOv8 RKNN postprocess path, but set class count to one.
The model should run on the full camera frame to find the chip body. The
defect model can then run on the cropped chip ROI.

The board source now defines chip ROI stream targets:

```text
rknn_chip_roi_camera_stream
rknn_chip_roi_maixcam_stream
```

The Windows live-view helper exposes matching profiles:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-roi-maixcam --conf 0.25
```

Current runtime note: the Windows `chip-roi` profiles default to the FP RKNN
because it has been verified to produce `chip` boxes on MaixCAM frames. The
INT8 RKNN is installed as the intended deployment target, but currently loads
without producing boxes and needs a separate quantization/postprocess fix.

## Two-Stage Flow

```text
camera frame
  -> chip ROI YOLOv8 RKNN
  -> crop/expand chip box
  -> existing four-class defect RKNN on ROI
  -> map defect boxes back to the original frame
```

INT8 is the deployment target. Keep FP RKNN on the board for debugging if INT8
confidence or box placement looks suspicious.

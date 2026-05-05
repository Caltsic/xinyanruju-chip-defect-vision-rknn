# Chip ROI Two-Stage Runtime Plan

Updated: 2026-05-04

## Goal

Build a board-side real-time path that uses the trained one-class `chip` model
to locate the chip first, then runs the existing four-class defect model only
inside the chip ROI.

## Current Baseline

- `chip-roi-maixcam` now defaults to split-output INT8 and returns chip boxes:
  - `model/chip_roi_yolov8_detect_split_int8.rknn`
  - outputs: `yolov8_boxes` + `yolov8_scores`
- The original single-output INT8 no-box issue was caused by `xywh` and `score`
  sharing one INT8 output scale. The split-output conversion fixes score
  quantization granularity.
- The defect model also has a split-output INT8 artifact:
  - `model/chipcheck_yolov8_detect_split_int8.rknn`
  - classes: `ZF-scratch`, `scratch`, `broken`, `pinbreak`.
- `chip-two-stage-maixcam` is implemented and deployed as the first board-side
  single-process two-model path.

## Target Runtime

```text
capture MJPG 1280x720
  -> decode to RGB888
  -> chip ROI INT8 model on full frame
  -> choose best chip box
  -> expand/square/clamp ROI
  -> defect INT8 model on ROI crop
  -> translate defect boxes back to full frame
  -> emit RYL1 detections:
       class 0: chip
       class 1: ZF-scratch
       class 2: scratch
       class 3: broken
       class 4: pinbreak
```

## Implementation Steps

Status on 2026-05-04: steps 1 through 6 are implemented and deployed.
The runtime path now includes board-side chip ROI smoothing, PC-side display
filtering, and cadence control. The default cadence is `chip-interval=3` and
`defect-interval=2`, which lifts the current two-stage stream from about 7 FPS
to about 10.3-10.9 FPS. `defect_conf=0.35` with `--display-max-defects 3` is
the cleaner observation command for the current real-camera distribution;
`0.25` keeps more candidates, and `0.05` remains useful only for low-threshold
diagnosis because it produces many large false positive boxes. Board-side
defect temporal filtering is now also deployed: each defect track requires
consecutive hits before output, holds briefly after misses, and matches
same-location boxes across classes to reduce `pinbreak/broken/scratch` flicker.

1. Diagnose and fix chip ROI INT8 before using FP for architecture work.
   - Add debug logging for top chip score, raw/dequantized score range, and xywh range.
   - Compare ONNX, FP RKNN, and INT8 RKNN on the same captured clean frame.
   - Check whether the issue is postprocess dequantization, score thresholding,
     channel layout, or RKNN calibration/conversion.
   - If the board-side postprocess is wrong, fix it and keep the existing INT8.
   - If the RKNN artifact is wrong, reconvert INT8 with a better calibration set.

2. Refactor YOLOv8 postprocess to runtime class count.
   - Current code uses compile-time `OBJ_CLASS_NUM`.
   - Two models in one process require class count `1` and `4` in the same binary.
   - For single-output YOLOv8, class count can be inferred from output channels as `channels - 4`.

3. Add a two-model context in `live_camera_yolo.cc`.
   - Load chip ROI model path and defect model path.
   - Keep independent `rknn_app_context_t` objects.
   - Run chip model first on full image.

4. Add dynamic ROI crop for defect inference.
   - Reuse the existing manual `--roi` crop path as the implementation base.
   - Expand chip box with a configurable margin.
   - Clamp to full frame and keep coordinates for back-mapping.

5. Emit chip + defect detections in one stream packet.
   - Chip result is class `0`.
   - Defect class ids are offset by `+1`.
   - Add PC profile `chip-two-stage-maixcam` with five labels.

6. Validate latency and stability.
   - `chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.25`
     runs with chip ROI INT8 + defect INT8.
   - 100-frame headless verification passed.
   - Current observed real-time speed is about 7.1-7.3 FPS.
   - MaixCAM MJPG bad frames can still occur, but the stream skips them instead
     of treating a single broken JPEG as fatal.

7. Stabilize observation.
   - Board-side chip ROI EMA smoothing reduces second-stage crop jitter.
   - PC-side display smoothing holds short-lived tracks, then applies
     class-agnostic display NMS and a max defect count so false-positive trails
     do not accumulate.
   - Raw frame-by-frame output can still be viewed with
     `--no-smooth-boxes --no-display-filter`.

8. Improve runtime cadence.
   - Chip ROI inference no longer needs to run every frame while the chip is
     static; default `--chip-interval 3`.
   - Defect inference can also be reused briefly; default
     `--defect-interval 2`.
   - Speed-priority static-scene command can use
     `--chip-interval 5 --defect-interval 3`, observed around 11.3-12.4 FPS.

9. Stabilize defect output on the board.
   - `DefectTemporalFilter` runs before the board emits RYL1 detections.
   - Default `--defect-confirm 2` suppresses one-frame noise.
   - Default `--defect-hold 3` keeps a confirmed defect briefly after misses.
   - `--defect-match-iou 0.10` and `--defect-match-center 0.55` match same
     physical boxes even when the predicted class changes.
   - `--defect-class-decay 0.85` keeps class votes stable instead of letting
     one frame immediately flip between defect classes.

## First Verification Command

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-maixcam --conf 0.25 --chip-conf 0.25 --defect-conf 0.35 --display-max-defects 3
```

Expected first-pass success:

```text
det >= 1
one chip box visible
defect boxes optional
no stream crash after 100+ frames
```

## Non-Goals For The First Two-Stage Version

- Do not add segmentation/masks yet.
- Do not rotate boxes yet.
- Do not promote FP chip ROI to the default deployment path unless INT8 is proven
  unsuitable for the current hardware. FP is for diagnosis and temporary fallback.
- Do not force PC-side preview adjustments into NPU input until measured useful.

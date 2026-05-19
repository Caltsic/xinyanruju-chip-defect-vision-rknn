# Seg Mask-Only Display And CVAT Capture Pipeline

## Date

2026-05-06

## User Problem

After the segmentation mask display was stabilized, the user reported two remaining issues:

- The current four-class defect accuracy is poor enough that model/data quality is now the main bottleneck.
- Four-class defect detection boxes appeared again in the real-time display, but the desired production view is mask-only / contour-only because the segmentation mask is more intuitive.
- It is time to start real-shot annotation for segmentation.
- Segmentation annotation is more complex than bbox review. The workflow must support adding objects, deleting objects, and flexibly adjusting mask/polygon ranges.
- The workload is large, so the expected workflow is real-shot capture first, then distribute annotation tasks to multiple people.

## Engineering Decision

The display problem and the data-closed-loop problem were separated:

- Display default:
  - Seg two-stage profiles should default to mask/contour display.
  - Defect rectangles and text labels should be hidden in the normal segmentation view.
  - Boxes and labels remain available for debugging through `--overlay-mode all`.
- Dataset workflow:
  - Use a single-machine / LAN CVAT deployment for segmentation annotation.
  - Only the host machine needs Docker/CVAT. Other annotators use a browser on the LAN and do not need Docker.
  - First real-shot segmentation round target: 800-1200 chip ROI images.
  - Capture both defect samples and normal/clean negative samples.
  - Use the current segmentation model only as pre-annotation; humans must refine, add, delete, and correct masks.
  - Label granularity: annotate only the truly visible defect area, not the whole chip edge, normal pin row, background, or model hallucination.

## Key Code Changes

`tools/adb_imx415_rknn_live_view.py`

- Added `OVERLAY_MODES`.
- Added CLI option:

```text
--overlay-mode all|mask|contour|mask-contour|boxes
```

- Two-stage segmentation profiles default to `mask-contour`.
- Other profiles keep the old all-overlay behavior by default.
- `draw_detections(...)` now controls mask fill, contour polyline, box rectangle, and label text according to overlay mode.
- The `drawn` count now tracks actually visible overlay output instead of treating hidden boxes/labels as zero drawn detections.
- Existing `--mask-fill auto|always|outline` behavior remains compatible with overlay mode.

`tools/chip_capture_gui/app.py`

- The PyQt GUI display toggle was split into:
  - `Draw masks/contours`
  - `Draw boxes/labels`
- Segmentation mode defaults to masks/contours on and boxes/labels off.
- Detection mode defaults to boxes/labels on and masks/contours off.
- The GUI maps these two toggles to the same overlay behavior used by the real-time CLI viewer.

`tools/chip_capture_gui/opencv_app.py`

- Added `--overlay-mode`.
- Segmentation defect model mode defaults to `mask-contour`.
- Detect mode defaults to `all`.
- The `O` hotkey now cycles:

```text
all -> mask-contour -> off -> all
```

- HUD now shows the current overlay state.

`tools/seg_cvat_pipeline.py`

- Added a three-stage CVAT/data-loop helper:
  - `capture`
  - `package-cvat`
  - `merge-coco`
- `capture` reads the board-side segmentation real-time stream and saves:
  - chip ROI crop images
  - full clean frames
  - preview images
  - per-image metadata
  - `manifest.csv`
  - YOLO-seg prelabels from the current model
- `package-cvat` chunks a captured session into CVAT task directories and creates COCO instance JSON plus optional task zip files.
- `merge-coco` accepts JSON files, directories, or zip inputs exported from CVAT, then merges them into a YOLOv8-seg raw dataset.
- `merge-coco` writes:
  - YOLOv8-seg images and labels
  - `data.yaml`
  - `names`
  - `merge_report`

`README.md` and `tools/chip_capture_gui/README.md`

- Added documentation for:
  - `--overlay-mode`
  - mask-only / mask-contour display
  - CVAT real-shot capture flow
  - capture, package, merge, and training command examples

## Verification

Syntax check:

```powershell
F:\anaconda\python.exe -m py_compile .\tools\adb_imx415_rknn_live_view.py .\tools\chip_capture_gui\app.py .\tools\chip_capture_gui\opencv_app.py .\tools\seg_cvat_pipeline.py
```

Result:

```text
exit code 0
```

CLI help checks:

```powershell
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py --help
F:\anaconda\python.exe -m tools.seg_cvat_pipeline --help
```

Result:

```text
both passed
```

Synthetic data pipeline smoke:

- Verified YOLO-seg prelabels.
- Ran `package-cvat --zip`.
- Ran `merge-coco` from the generated zip.
- Class ids and polygon coordinates were preserved through the round trip.

Board-side headless default seg overlay check:

```text
profile: chip-two-stage-seg-imx678
default overlay: mask-contour
frames: 45
snapshot: captures/seg_overlay_mask_contour_default_annotated.jpg
final status: det 4/2 | frame 44
```

Observed result:

- The default segmentation view had no defect rectangle and no defect text label.
- Only mask/contour overlay remained visible.

Board-side debug overlay comparison:

```text
overlay: --overlay-mode all
frames: 45
snapshot: captures/seg_overlay_all_debug_annotated.jpg
final status: det 3/3 | frame 44
```

Observed result:

- Defect boxes and labels were restored for debug view.

Real board capture smoke:

```powershell
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py capture --count 2 --stride 10 ...
```

Result:

```text
exit code 0
saved=2 seen=20 skipped_no_chip=0 elapsed=3.5s
```

Output counts from the temporary capture directory:

- `images`: 2
- `labels`: 2
- `images_full`: 2
- `previews`: 2
- `meta`: 2
- `manifest.csv`: 2 data rows
- Each label had 2 pre-annotated objects.
- Total pre-annotated objects: 4.
- The temporary smoke-test directory was cleaned up after validation.

PowerShell note:

- Headless real-time commands may still show `NativeCommandError` or exit code `1` when stderr is merged into PowerShell output.
- For this project, if the command reports processed frames and saves the requested snapshot, that stderr wrapping alone must not be treated as a failed run.

## Current Recommended Commands

Default real-time segmentation view, mask/contour only:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

Debug view with boxes and labels restored:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20 --overlay-mode all
```

Real-shot capture for first segmentation annotation session:

```powershell
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py capture --count 1000 --stride 8 --output-dir .\chip_seg\captures\session_001
```

Package captured data into CVAT tasks:

```powershell
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py package-cvat --input-dir .\chip_seg\captures\session_001 --output-dir .\chip_seg\cvat_tasks\session_001 --chunk-size 100 --zip
```

Merge CVAT exports into a YOLOv8-seg raw dataset:

```powershell
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py merge-coco --inputs .\chip_seg\cvat_exports\session_001 --output-dir .\cloud_training\yolov8_seg_rknn\dataset_raw\imx678_seg_session_001 --overwrite
```

## Remaining Risks And Next Steps

- CVAT deployment itself was not executed in this round.
- The next practical step is to create the first small CVAT task with 30-50 real-shot samples and let annotators test the add/delete/edit mask workflow.
- The annotation standard should be validated on that small task before distributing 800-1200 images.
- Current segmentation pre-annotation accuracy is not high; it should be treated only as a starting point for human refinement.
- After the first completed annotation batch, retrain YOLOv8-seg, convert to RKNN, deploy to the Taishanpai RK3576 board, and verify again with IMX678 real-time mask-only display.

## Outcome

This round completed the display-side fix and prepared the data-collection/annotation tooling needed for a segmentation data loop:

- Normal seg real-time display now defaults to mask/contour only.
- Debug boxes and labels are still available explicitly.
- CVAT-oriented capture, task packaging, and export merge tooling now exists.
- The immediate model-quality path is no longer more threshold tuning; it is real-shot data capture, human-refined segmentation labels, retraining, and board-side validation.

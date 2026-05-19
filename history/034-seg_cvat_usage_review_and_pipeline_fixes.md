# Seg CVAT Usage Review And Pipeline Fixes

## Date

2026-05-06

## User Request

After the mask-only display and CVAT capture pipeline were implemented, the user asked for two follow-up actions:

- Explain concretely how to use the new real-shot segmentation capture / CVAT annotation workflow.
- Re-check the implementation for defects before starting real data collection and multi-person annotation.

This archive records the visible review findings, fixes, validation results, and remaining risks from that follow-up. It does not record hidden reasoning.

## Review Findings

The review found two high-risk issues that needed to be fixed or explicitly avoided before formal annotation.

### High Risk 1: CVAT COCO Zip Structure

Original risk:

- `tools/seg_cvat_pipeline.py` produced zip files with paths under `part_001/...`.
- The generated package layout was effectively:

```text
part_001/images/...
part_001/annotations/instances_default.json
```

- CVAT's expected COCO task zip layout is rooted at:

```text
images/default/...
annotations/instances_default.json
```

Impact:

- A zip with the extra `part_001` directory layer could fail direct CVAT import or require manual unpacking and upload.
- This would be especially disruptive for the planned multi-person annotation workflow.

### High Risk 2: CVAT Brush/Mask May Export RLE

Original risk:

- `merge-coco` only handled COCO annotations where `segmentation` was a polygon list.
- CVAT can export brush/mask annotations as COCO RLE masks, especially when mask tools or `is_crowd` style data is involved.
- The old merge logic skipped non-list `segmentation` values.

Impact:

- RLE mask annotations could be silently dropped.
- That would produce empty YOLO label files or missing objects.
- Training data would be badly polluted because human-corrected masks could disappear during merge.

Short-term avoidance before the fix would have been:

- Force annotators to use Polygon only.
- Do not use Brush/Mask.
- Do not mark objects as `is_crowd`.

After the fix, polygon annotation remains preferred for precise chip defects, but RLE exports are now handled by the merge tool instead of being silently lost.

## Fixes Completed

The following fixes were applied to `tools/seg_cvat_pipeline.py` by the implementation worker. This archive only records them; this archiving pass did not modify source files.

### CVAT Zip Layout Fix

`package-cvat` was fixed so the generated CVAT zip root matches the expected COCO structure:

```text
images/default/<image files>
annotations/instances_default.json
```

The COCO `file_name` values were also aligned to the same subset-relative convention:

```text
default/<image file>
```

This makes the zip usable as the direct CVAT import/package format, instead of requiring a manual workaround with `part_001/images`.

### RLE Mask Merge Fix

`merge-coco` was extended to support COCO RLE dictionary masks.

Behavior after the fix:

- Polygon-list annotations are still supported.
- RLE dict annotations are decoded into a binary mask.
- The binary mask is converted back to contours with OpenCV `findContours`.
- Contours are converted to YOLO segmentation polygons.
- Merge statistics now include collection stats so skipped/decoded cases are visible in `merge_report.json`.

This prevents CVAT brush/mask exports from being silently dropped.

### Capture Light Setup Fix

Original medium risk:

- `capture` accepted light-related options, but brightness was only written to metadata.
- It did not actually set the WS2812 ring light.

Fix:

- `capture` now actually configures WS2812 lighting before acquisition.
- Added options:

```text
--light-rgb
--light-count
--light-device
--no-light-setup
```

Operational effect:

- Capture conditions are less likely to drift from the real-time test conditions.
- `--no-light-setup` is available when the operator intentionally wants to preserve an already configured light state.

### Capture Stop Conditions And Progress Fix

Original medium risk:

- `capture` could run indefinitely when no chip was detected, thresholds were too strict, or `--require-defect` was enabled with no defect appearing.

Fix:

- Added hard stop / diagnostic options:

```text
--timeout-sec
--max-frames
--progress-interval
```

Operational effect:

- Capture can stop automatically after a time budget or frame budget.
- Long sessions report periodic progress.
- Failed chip detection does not leave an unattended process running forever.

### Manifest Portability Fix

Original medium risk:

- `manifest.csv` stored absolute paths.
- If a capture session was moved to another disk or another machine, `package-cvat` could try to read stale absolute paths even when the session directory itself was complete.

Fix:

- New manifests store relative paths.
- `read_capture_items` remains backward compatible:
  - It can read old absolute-path manifests.
  - If the old absolute path is missing, it falls back to files under the current session directory, such as `images/<name>` and `labels/<stem>.txt`.

Operational effect:

- Capture directories can be moved, zipped, shared, and packaged later with fewer path failures.

### ROI Edge Prelabel Fix

Original medium risk:

- Defect prelabel polygons near the chip ROI edge were handled by filtering points outside the crop.
- Filtering points is not geometric clipping; it can deform or drop polygons near ROI boundaries.

Fix:

- Prelabel polygons are now clipped against the ROI rectangle.
- This preserves valid partial polygons instead of losing edge-touching defects.

Operational effect:

- Model-generated prelabels near the ROI boundary are more usable as CVAT starting points.
- Human annotators still need to inspect and correct them.

### Keep-No-Chip Full-Frame Crop Fix

Original bug/risk:

- In the no-chip fallback path, full-frame crop dimensions could be wrong.

Fix:

- `keep-no-chip` full-frame crop now uses the actual image width and height.

Operational effect:

- Negative or fallback samples saved without a detected chip have consistent crop geometry and metadata.

## Current Usage

### 1. Confirm Real-Time Segmentation View

Before formal capture, verify that the board, IMX678 UVC camera, light, chip ROI, and segmentation display are stable.

Default production-style view, mask/contour only:

```powershell
cd F:\WORKSPACE\chipCheck\-IMX415_Vision
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

Debug view with boxes and labels:

```powershell
cd F:\WORKSPACE\chipCheck\-IMX415_Vision
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20 --overlay-mode all
```

Use the debug view only to diagnose thresholds, class scores, and ROI placement. Normal display should remain mask/contour only.

### 2. Run A Small Capture Pilot First

Use a small pilot session before assigning annotation work to multiple people.

Recommended first pilot:

```powershell
cd F:\WORKSPACE\chipCheck\-IMX415_Vision
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py capture --output-dir .\chip_seg\captures\pilot_001 --count 50 --stride 8 --timeout-sec 300 --max-frames 2000 --progress-interval 50 --defect-conf 0.35 --light-rgb 255,255,255 --light-brightness 50
```

Important behavior:

- `images/` contains chip ROI crops for annotation/training.
- `images_full/` contains full clean frames for traceability.
- `previews/` contains visual preview images.
- `labels/` contains YOLO-seg prelabels from the current model.
- `meta/` contains per-image capture metadata.
- `manifest.csv` records the capture set with relative paths.

The current segmentation model's labels are only pre-annotations. Annotators must correct them.

### 3. Package The Pilot For CVAT

Create a CVAT-ready package:

```powershell
cd F:\WORKSPACE\chipCheck\-IMX415_Vision
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py package-cvat --input-dir .\chip_seg\captures\pilot_001 --output-dir .\chip_seg\cvat_tasks\pilot_001 --chunk-size 50 --zip
```

Expected package structure inside the zip:

```text
images/default/<image files>
annotations/instances_default.json
```

Upload this zip to CVAT as a COCO instance segmentation task.

### 4. CVAT Annotation Rules

Use these rules for the pilot and later full batches:

- Label classes remain four defect classes:
  - `ZF-scratch`
  - `scratch`
  - `broken`
  - `pinbreak`
- Annotate only the actual visible defect area.
- Do not include normal chip edge, normal pin rows, background, reflection, or non-defect texture.
- Delete model hallucinations.
- Add missed defects.
- Adjust polygon/mask boundaries tightly around the visible defect.
- Polygon annotation is still preferred for precise small defects.
- Brush/mask annotation is now safer because RLE merge is supported, but the pilot export must verify the full round trip before mass annotation.

### 5. Export From CVAT And Merge

After annotation, export from CVAT as COCO instance segmentation.

Place exported zip/json files under a collection directory, for example:

```text
.\chip_seg\cvat_exports\pilot_001\
```

Merge into YOLOv8-seg dataset format:

```powershell
cd F:\WORKSPACE\chipCheck\-IMX415_Vision
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py merge-coco --inputs .\chip_seg\cvat_exports\pilot_001 --output-dir .\chip_seg\datasets\pilot_001_yolo_seg --overwrite
```

Inspect:

```text
.\chip_seg\datasets\pilot_001_yolo_seg\merge_report.json
.\chip_seg\datasets\pilot_001_yolo_seg\data.yaml
.\chip_seg\datasets\pilot_001_yolo_seg\train\labels
.\chip_seg\datasets\pilot_001_yolo_seg\valid\labels
```

The merge report should be checked for:

- number of images
- number of annotations
- polygon annotations collected
- RLE masks decoded
- skipped annotations
- empty labels
- class distribution

### 6. Scale To First Formal Batch

After the 30-50 image pilot import/annotation/export/merge round trip is confirmed, scale to the first useful batch.

Recommended first formal batch:

```powershell
cd F:\WORKSPACE\chipCheck\-IMX415_Vision
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py capture --output-dir .\chip_seg\captures\session_001 --count 800 --stride 8 --timeout-sec 3600 --max-frames 20000 --progress-interval 100 --defect-conf 0.35 --light-rgb 255,255,255 --light-brightness 50
```

Then package in manageable chunks:

```powershell
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py package-cvat --input-dir .\chip_seg\captures\session_001 --output-dir .\chip_seg\cvat_tasks\session_001 --chunk-size 100 --zip
```

Each generated part can be assigned to an annotator.

## Verification Completed

### Local Syntax And CLI

`py_compile` passed after the fixes.

Help output checks passed for the CVAT pipeline script.

### Synthetic Package/Merge Checks

Synthetic validation covered:

- `package-cvat` zip root paths.
- `images/default/...` layout.
- `annotations/instances_default.json` layout.
- COCO `file_name` values using `default/<image>`.
- Old absolute-path manifest fallback.
- RLE dict merge into YOLO polygon labels.
- `merge_report.json` collection statistics.

### Board Smoke Checks

Board-side smoke verification covered:

- Capture invokes actual WS2812 light setup.
- `--max-frames` can stop a capture session instead of running indefinitely.
- `keep-no-chip` save path works.

Observed output chain for `keep-no-chip` validation:

- `images`: 1
- `labels`: 1
- `images_full`: 1
- `previews`: 1
- `meta`: 1
- `manifest.csv`: 1 row
- Manifest paths were relative.

## Remaining Risks

- During the board smoke test, the current real chip scene did not detect a chip. Before formal capture, the operator must use the real-time window to confirm chip ROI is stable under the current camera, exposure, lighting, and threshold settings.
- The first CVAT task should still be only 30-50 images. Do not send 800-1200 images to multiple annotators until the import, edit, export, and merge loop has been verified on that pilot.
- RLE support reduces the risk of dropped brush/mask annotations, but polygon annotation is still the safer default for small chip defects unless brush output has been validated on a real CVAT export.
- Current model prelabels are not trusted labels. They are only an annotation acceleration aid.
- After the first corrected dataset is merged, retraining and RKNN conversion are still required before judging model quality on the board.

## Outcome

The follow-up review found real pipeline risks before formal annotation started. The major issues were addressed:

- CVAT zips now use a direct COCO-compatible root layout.
- CVAT RLE mask exports are decoded and converted instead of silently dropped.
- Capture now configures lighting, has bounded stop conditions, reports progress, writes portable manifests, clips edge prelabels, and handles no-chip full-frame fallback correctly.

The workflow is now suitable for a 30-50 image CVAT pilot. Formal multi-person annotation should start only after that pilot confirms stable chip ROI and clean CVAT import/export/merge behavior.

## Final Label Naming Clarification

The README CVAT label instructions were clarified after this review.

The intended class order is:

- `0 -> ZF-scratch`
- `1 -> scratch`
- `2 -> broken`
- `3 -> pinbreak`

In CVAT, label names should be entered as the right-side names only:

- `ZF-scratch`
- `scratch`
- `broken`
- `pinbreak`

Do not include the numeric prefixes in CVAT label names. The merge script maps categories by label name first. It has a `category_id` order fallback, but formal multi-person annotation should not depend on that fallback because different CVAT imports/exports or manual task setup can shift numeric ids while preserving names.

# Chip OBB Manual CVAT Task Preparation

Updated: 2026-05-09

## Summary

This archive records the corrected task direction and the completed preparation of chip OBB CVAT packages for manual annotation. The current task is not to display an OBB real-time window; it is to prepare existing major chip datasets so the chip OBB labels can be manually corrected in CVAT.

No passwords, keys, cloud SSH credentials, or hidden credentials are recorded here.

## Scope Correction

User correction:

- The current task is not OBB real-time window display.
- The current task is preparation for manual correction of chip OBB annotations.
- The preparation must include the currently available major chip datasets.

## Added Files

New plan file:

```text
plans/chip_obb_cvat_preparation_20260509.md
```

New script:

```text
tools/prepare_chip_obb_cvat_tasks.py
```

## Script Purpose

`tools/prepare_chip_obb_cvat_tasks.py` collects full-frame chip samples from:

```text
chip_roi/generated/cloud_chip_roi_yolo
chip_roi/generated/gui_capture
chip_seg/captures
```

For `chip_seg/captures`, it uses `images_full` plus `meta/*.json crop_box` rather than ROI crop-only defect training images. The engineering judgment is that chip localization requires full-frame context, and the corresponding full-frame `images_full` sources already exist.

The script:

- reads full-frame images and source metadata;
- deduplicates images by SHA1;
- writes CVAT task packages with a single `chip` label;
- creates initial editable chip annotations as four-point polygon / YOLO OBB labels;
- estimates the initial rotated chip polygon from existing HBB labels or capture `crop_box` with `minAreaRect`;
- falls back to horizontal four-point boxes when rotated estimation fails.

## Output Directory

```text
chip_roi/cvat_obb_tasks_20260509/
```

## Run Command

```powershell
F:\anaconda\python.exe .\tools\prepare_chip_obb_cvat_tasks.py --output-dir .\chip_roi\cvat_obb_tasks_20260509 --chunk-size 150 --zip --overwrite --preview-count 24
```

## Result Counts

```text
collected_samples=5366
readable_samples=5366
unique_images=2991
duplicates_removed=2375
total_initial_chip_annotations=2940
parts=20
```

Source counts:

```text
chip_roi_yolo=1178
chip_roi_gui_capture=382
seg_capture_full=3806
```

Part statistics:

- `part_001` through `part_019`: 150 images each.
- `part_020`: 141 images.
- Total: 20 zip packages.
- The first 8 packages contain a small number of empty annotations / negative samples; they are intentionally retained for manual confirmation.

## Validation

Validation summary:

```text
parts=20 zips=20 images=2991 coco_annotations=2940 yolo_obb_labels=2940
summary consistent
validation ok
```

Visual spot check:

- `previews/part_001` preview showed the initial rotated boxes generally covering chips.
- A temporary `part_015` preview also showed the initial rotated boxes generally covering chips.
- These initial annotations are acceptable as manual correction starting points.

## Output Structure

Each part contains:

```text
images/default/*.jpg
labels/*.txt
annotations/instances_default.json
annotations.xml
labels.txt
manifest.csv
README.md
```

Top-level output contains:

```text
README.md
summary.json
previews/*.jpg
```

## CVAT Usage

Create one CVAT Task for each:

```text
part_*.zip
```

Task label:

```text
chip
```

If the pre-annotations are not loaded automatically, import either:

```text
annotations/instances_default.json
```

as COCO 1.0, or:

```text
annotations.xml
```

as CVAT for images.

Manual annotation rule:

- Only correct the outer chip contour / rotated four points.
- Add a chip polygon when a complete chip is missing.
- Delete mistaken labels and images without a complete chip.
- Normal single-chip images should keep one `chip` polygon.

## Current Conclusion

The CVAT packaging stage for manual chip OBB annotation is complete. The generated packages cover the existing major full-frame chip sources, avoid duplicate images, and provide initial editable chip polygons suitable for human correction before OBB model training.

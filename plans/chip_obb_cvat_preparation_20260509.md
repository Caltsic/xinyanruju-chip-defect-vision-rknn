# Chip OBB CVAT Preparation 2026-05-09

## Goal

Prepare current chip-class data for distributed manual annotation in CVAT so the chip locator can be retrained as an oriented-box model.

## Scope

- Include existing chip ROI full-frame YOLO datasets.
- Include IMX678 segmentation capture full-frame images via `images_full` plus `meta/*.json crop_box`.
- Use one label only: `chip`.
- Write task chunks of 150 images.
- Preserve initial annotations as editable four-point chip polygons.
- Keep ROI crop-only defect segmentation training images out of the main chip locator package when their full-frame capture counterparts are available.

## Output

Default output directory:

```text
chip_roi/cvat_obb_tasks_20260509/
```

Each part:

```text
part_001/
  images/default/*.jpg
  labels/*.txt
  annotations/instances_default.json
  annotations.xml
  labels.txt
  manifest.csv
  README.md
part_001.zip
```

## Validation

- Count source images, unique images, packaged images and initial chip annotations.
- Verify every image in every part has an entry in COCO and XML.
- Verify every YOLO OBB label has 9 columns and normalized coordinates.

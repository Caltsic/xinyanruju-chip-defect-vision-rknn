# Chip OBB CVAT Project-Level Export Check

Updated: 2026-05-09

## Summary

This archive records the check of a CVAT project-level COCO 1.0 export for the chip OBB manual annotation work.

No passwords, keys, cloud SSH credentials, or hidden credentials are recorded here.

## Input Export

User-provided CVAT export zip:

```text
chip_roi/export/project_3_dataset_2026_05_09_10_15_32_coco 1.0.zip
```

Local original preparation package used for comparison:

```text
chip_roi/cvat_obb_tasks_20260509
```

## Conclusion

The project-level full export can theoretically be used directly as the recycling / conversion entry point, so each CVAT task does not need to be exported separately.

However, the current project-level zip contains fewer images than the local original preparation package. The missing images and annotation changes need user confirmation before treating this export as the final source.

If the missing images / deleted labels were intentional manual cleanup in CVAT, this project-level zip can be used for the next YOLO OBB conversion stage. If not, CVAT should be checked to confirm whether the affected parts were imported completely or whether images were accidentally deleted.

## Zip Check Result

Zip-level facts:

```text
entries=2957
top-level=annotations, images
coco_json=annotations/instances_default.json
zip_images=2956
coco_images=2956
coco_annotations=2899
categories=chip
```

Original preparation package statistics:

```text
expected_images=2991
expected_initial_annotations=2940
```

Comparison result:

```text
missing_images=35
extra_images=0
export_unannotated_images=57
expected_unannotated_images=51
segmentation_coord_distribution={8: 2897, 10: 2}
```

## Per-Part Image Differences

Parts with fewer images in the project-level export:

| Part | Missing images |
| --- | ---: |
| `part_004` | 1 |
| `part_005` | 2 |
| `part_008` | 2 |
| `part_009` | 6 |
| `part_010` | 4 |
| `part_011` | 10 |
| `part_012` | 2 |
| `part_019` | 1 |
| `part_020` | 7 |

All other parts match the expected image count.

## Annotation Changes

There are 26 images whose annotation counts differ from the initial preparation package.

Observed change types:

- Some initial negative samples were manually supplemented with a `chip` annotation.
- Some initial positive samples were deleted to empty annotations.

These may be valid manual corrections, but they require user confirmation before downstream conversion.

## Non-4-Point Polygons

Two polygons are not four-point polygons:

```text
seg_capture_full_gui_session_20260506_163553_seg_0685_jpg_7149687d.jpg
seg_capture_full_gui_session_20260506_163553_seg_0821_jpg_ca6d3b02.jpg
```

Both are 5 points / 10 coordinates.

If the four-point rule is strict, these should be fixed in CVAT. If they are not fixed, downstream conversion can regularize them to OBB with `minAreaRect`, but keeping the annotation rule uniform is preferred.

## Recommendation

Use the project-level zip for YOLO OBB conversion only after confirming that the missing images and deleted labels are intentional manual edits.

If the missing images / deleted labels are not intentional, return to CVAT and check whether the affected parts were imported completely or whether images were accidentally deleted.

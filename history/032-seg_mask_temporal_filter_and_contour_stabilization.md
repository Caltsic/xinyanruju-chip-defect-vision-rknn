# Seg Mask Temporal Filter And Contour Stabilization

## Date

2026-05-06

## User Problem

The user reported that four-class defect segmentation masks are more intuitive than detection boxes for real-time display, but the current mask results jump on a static scene: sometimes correct, sometimes wrong. This looked similar to the early two-stage box display before temporal filtering was added.

The Taishanpai 3M RK3576 board stayed connected during the investigation, so board-side deployment and verification were allowed directly.

## Persistent Archiving Rule

During this task, the project rule for durable history archiving was persisted in:

- `AGENTS.md`
- `history/000-history-index-and-rules.md`

Rule summary:

- After each meaningful task phase, dispatch a sub-agent to review the chief engineer's visible current context, key file changes, command results, outcomes, and risks, then archive reusable engineering facts into `history/`.
- When a new user-reported problem is solved, create or update a clearly named `history/NNN-*.md` entry with symptoms, root cause, fix, touched files and board paths, verification command, result, and residual risks.
- History archives record visible context, file changes, command results, and engineering facts only. They must not include hidden reasoning or unreported internal chain-of-thought.

## Root Cause Layers

1. The old segmentation branch directly cached raw `defect_results` and `defect_seg_results`, bypassing the `DefectTemporalFilter` already used by the detect branch.
2. The PC-side `DetectionSmoother` previously stored only box, class, and score. If smoothing was enabled for segmentation, contour data would be dropped, so smoothing had been disabled by default for seg display.
3. The board-side `postprocess.cc` previously built mask contours by sorting boundary points by angle around the center. For thin defects, broken shapes, L-shaped regions, or multi-segment pin rows, this can create self-crossing polygons and large false triangle fills.
4. The first contour-chain repair could still accept an unclosed path. PC `fillPoly` then force-closed the open contour and produced large false filled regions.
5. PC smoothing `hold` under the seg profile could keep already-disappeared low-confidence candidates for one or two extra display frames, creating `drawn > raw` or ghost-mask behavior.

## Key Code Changes

`rknn_work/board_yolo11_src/examples/yolo11/cpp/live_camera_yolo.cc`

- Added and enabled `SegDefectTemporalFilter`.
- The seg branch now runs `seg_defect_filter.update(...)` before caching results.
- The filter supports confirm, hold, class voting, and box EMA.
- Streamed contours now come from the filtered segmentation cache rather than raw current-frame seg output.

`rknn_work/board_yolo11_src/examples/yolo11/cpp/postprocess.cc`

- Mask contour construction changed to boundary edge chaining.
- Added direction and turn-priority handling.
- Only closed loops are accepted.
- When mask contour construction fails, the code no longer calls `fill_bbox_contour(seg)`, avoiding the old behavior of displaying the bbox as if it were a real mask contour.

`tools/adb_imx415_rknn_live_view.py`

- `DetectionTrack` now preserves `polygon`, `contour`, and `area`.
- `smooth_boxes` now defaults on for two-stage seg profiles as well.
- Added `--mask-fill auto|always|outline`.
- `--mask-fill auto` skips filled masks for contours that look unsafe, including self-intersection, long closing edge, or untrusted area ratio; unsafe contours are drawn as outlines instead.
- Seg profiles now default to `smooth_hold=0` and `smooth_min_hits=3`, reducing PC-side low-confidence ghost display.

## Board Deployment

Latest board build:

```text
/userdata/chipcheck_build/build_yolo11_closed_loop/rknn_chip_two_stage_maixcam_stream
```

Deployed board binary:

```text
/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream
```

Deployed binary SHA256:

```text
8846480855b379d3cee25281376ff24d99f1cc98dc8dab65eb5d219535d67343
```

Backup before closed-loop deployment:

```text
/userdata/rknn_yolo11_demo/rknn_chip_two_stage_maixcam_stream.bak_pre_closed_loop_20260506
```

Backup SHA256:

```text
1dec6a900fc6bceef5355f7dfb2cb97e2643b104d1a529c1f1f84423927cd034
```

## Verification Command Profile

Core verification parameters:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-seg-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20 --frames 90 --headless
```

## Verification Screenshots And Results

- `captures/seg_filter_closed_loop_auto_conf045_annotated.jpg`
  - Closed-loop contour validation plus `--mask-fill auto`.
  - 90 frames processed.
  - Final status was `det 6/6`.
  - Large triangle false fills were mostly eliminated.

- `captures/seg_filter_closed_loop_outline_conf045_annotated.jpg`
  - Outline-mode comparison.
  - 90 frames processed.
  - Final status was observed as `det 6/7`.
  - This exposed the remaining PC-side hold ghost behavior.

- `captures/seg_filter_pc_no_hold_auto_conf045_annotated.jpg`
  - PC no-hold defaults plus `--mask-fill auto`.
  - 90 frames processed.
  - Final status was `det 6/6`.
  - No obvious large triangle false fill remained.

- `captures/seg_filter_pc_no_hold_outline_conf045_annotated.jpg`
  - Outline mode with PC no-hold defaults.
  - 90 frames processed.
  - Final status was `det 6/6`.

## Outcome

The major static-scene instability sources found in this round were handled:

- Board-side segmentation output now uses temporal filtering instead of direct raw cache.
- PC-side smoothing can retain segmentation contours instead of dropping them.
- Closed-loop contour validation prevents open paths from being force-filled into large false masks.
- `--mask-fill auto` reduces unsafe filled overlays while still preserving useful contour visualization.
- Seg profile no-hold display defaults remove the most visible PC-side ghost effect.

The large false triangle fills and PC display ghost behavior are considered fixed for the verified scenario.

## Remaining Engineering Risk

The remaining visible issues are mainly model and data quality limitations:

- Broken chip edges and pin rows can still produce multiple candidates.
- Some segmentation contours are still large or jagged because the model predicts imperfect mask regions.
- Better production quality should come from new real-shot data, human-refined segmentation labels, model retraining, and possibly transmitting true masks or multiple contours instead of only one simplified contour per defect.

## Notes

- PowerShell `NativeCommandError` was caused by stderr merging and script log wrapping. In this task it should not be treated as a failed verification by itself.
- The relevant verification runs still reported `Processed frames: 90` and saved the requested screenshots.

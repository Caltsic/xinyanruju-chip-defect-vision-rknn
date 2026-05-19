# GUI Manual Seg Sample And Local CVAT Start

## User Question

The user pointed out that automatic continuous capture is not suitable when samples are changed by hand: if the same chip stays in view, repeated frames will be captured as near-duplicate samples. The user also asked whether CVAT can be started locally on this machine.

## Investigation

- The existing chip capture GUI was originally a single-image chip ROI confirmation tool.
- It allowed live detection, frame capture, ROI adjustment, accept/negative review, and dataset saving for chip ROI work.
- It was not originally the entry point for segmentation CVAT sample capture.
- `tools/seg_cvat_pipeline.py capture` is an automatic frame-stream capture path. It is suitable when feeding hardware or the scene keeps changing.
- For manual sample replacement, automatic capture can repeatedly save the same chip unless the user runs very small batches or restarts capture per sample.

## Implemented Result

GUI-based manual segmentation sample saving was implemented.

Changed code files in the implementation phase:

- Added `tools/chip_capture_gui/seg_sample.py`.
- Updated `tools/chip_capture_gui/app.py`.
- Updated `tools/chip_capture_gui/opencv_app.py`.
- Updated GUI and project README usage notes.

The new shared saver reuses existing segmentation capture helpers from `tools/seg_cvat_pipeline.py`, including:

- `best_chip_box`
- `defect_prelabels`
- `draw_prelabel_preview`
- `write_jpeg`
- `write_manifest_row`
- `session_relative`
- `CLASS_NAMES`

PyQt GUI behavior:

- Adds a `Save Seg Sample` button.
- The intended workflow is to start live detection, place or replace one chip sample, inspect the live segmentation overlay, then click `Save Seg Sample` once.
- After saving, the user manually replaces the chip and clicks the button again.

OpenCV GUI behavior:

- Adds live-mode `V` or `S` shortcut to save one segmentation sample.
- In review mode, `S` still keeps its existing ROI movement behavior.

Default output structure:

```text
chip_seg/captures/gui_session_YYYYMMDD_HHMMSS/
  images/
  labels/
  images_full/
  previews/
  meta/
  manifest.csv
```

Saved file names increment in one GUI session, for example `seg_0001`, `seg_0002`, and so on. Existing files are checked before saving so the writer does not overwrite previous samples.

If no chip ROI is detected, the GUI does not save a sample and does not fallback to saving the full frame.

## Verification

Validation reported for the implementation:

- `py_compile` passed for `tools/chip_capture_gui/seg_sample.py`, `tools/chip_capture_gui/app.py`, `tools/chip_capture_gui/opencv_app.py`, and `tools/seg_cvat_pipeline.py`.
- PyQt and OpenCV GUI module imports passed.
- A constructed-frame smoke test successfully generated `seg_0001` and `seg_0002`.
- The generated manifest used relative paths.
- Metadata fields were present.
- No-chip input returned without saving.
- Real board non-interactive validation confirmed `SegSampleWriter` saved `seg_0001` from one live frame.
- In that board validation, `images`, `labels`, `images_full`, `previews`, and `meta` each contained one output, and `manifest.csv` used relative paths.

## Local CVAT Start

Local CVAT startup was checked and completed.

Observed environment and actions:

- Docker Desktop was running.
- CVAT was pulled locally and checked out to release `v2.64.0`.
- `docker compose up -d` completed successfully.
- `http://localhost:8080` returned HTTP 200.
- Superuser was created:
  - username: `admin`
  - password: `ChipCheck@2026`
- CVAT containers were reported healthy/running.

Local browser URL:

```text
http://localhost:8080
```

## Usage Notes

- Keep Docker Desktop running while using local CVAT.
- For local single-machine annotation, use `http://localhost:8080`.
- For multi-person LAN annotation, set `CVAT_HOST` to the host machine's LAN IP before starting CVAT and allow inbound access to port `8080` in the Windows firewall.
- Recommended first loop:
  1. Use the GUI manual save path to collect 30-50 segmentation samples.
  2. Run `package-cvat` on the GUI capture session.
  3. Import the package into CVAT.
  4. Annotate and export once.
  5. Run `merge-coco` and inspect `merge_report.json`.
  6. Only then expand to the larger 800-1200 image collection.

## Current Recommendation

For manual chip replacement, prefer GUI one-sample-at-a-time saving over automatic `seg_cvat_pipeline.py capture`.

Use automatic `capture` only when the physical scene changes continuously, such as with feeding hardware, a turntable, or another repeatable motion setup.

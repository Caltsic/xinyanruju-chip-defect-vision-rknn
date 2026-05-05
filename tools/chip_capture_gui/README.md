# Chip Capture GUI

Run from the project root:

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui
```

The default PC GUI is PyQt5 based and keeps using the ADB backend. It is the
preferred path for real chip ROI capture, quick labeling, and two-stage live
observation from Windows.

OpenCV simplified interface:

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui --opencv --backend adb
```

Board-local HDMI interface:

```bash
cd /userdata/chipcheck_vision
python3 -m tools.chip_capture_gui --opencv --backend local --fullscreen
```

The board-local backend starts the stream binary directly on TaishanPi and does
not use ADB `exec-out` for frames.

Default live stream:

```text
chip-two-stage-imx678
chip_conf=0.25
defect_conf=0.45
defect_confirm=3
display_max_defects=20
```

This is equivalent to the current command-line live view:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-imx678 --conf 0.25 --chip-conf 0.25 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20
```

Default output:

```text
chip_roi/generated/gui_capture/
```

Each capture is saved with an automatic sequence name:

```text
images/chip_0001.jpg
labels/chip_0001.txt
meta/chip_0001.json
previews/chip_0001.jpg
manifest.csv
```

Workflow:

1. Start camera.
2. Use `Live Detect` to observe chip + defect boxes while tuning Advanced sliders.
3. Click `Capture ROI` to freeze the current adjusted view.
4. The GUI saves that adjusted frame and creates an initial `chip` box.
5. Adjust the box if needed.
6. Press `Enter` or click `Accept`; press `Delete` or click `Negative` for empty/invalid frames.

Current capture defaults:

```text
Light 50%
Brightness -6
Contrast 1.28
Gamma 0.91
Saturation 0.30
Sharpness 0.85
Denoise 6
```

`Sync view to NPU input` is enabled by default. With the default two-stage MaixCAM stream, Brightness/Contrast/Gamma/Saturation/Sharpness are written to the board-side `/tmp/chip_input_adjust.conf`, so the live frame shown by the GUI matches the RGB888 frame used by chip ROI and defect RKNN inference.

Denoise and CLAHE are not sent to the board-side NPU input. Denoise remains a GUI observation/capture option only; the old NLM denoise path was too slow for 1280x720 realtime preview and could make the GUI appear frozen while the slider was being dragged.

`Save adjusted capture` is enabled by default. Captured training images are
therefore saved from the current visible frame, and the exact settings are
written into each metadata JSON. Disable it if you need raw camera frames.

Quick presets in Advanced:

```text
Pins    higher local edge clarity for pin observation
Text    higher contrast and restrained saturation for silk-screen observation
Damage  conservative default for broken/scratch observation
Reset   current project default
```

Board-side input adjustment costs full-frame RGB processing time. With the current default `Sharpness 0.85`, the two-stage MaixCAM path has been measured around `8.3-9.2 FPS`; lowering Sharpness or setting it to `0` is the first speed/clarity tradeoff to try.

Controls:

```text
A/D/W/S  move the current chip box
+/-      scale the current chip box
Enter    accept the current box
Delete   mark the frame as a negative sample
Esc/q    not used for saving; close the window normally
```

OpenCV interface controls:

```text
Tab       select Brightness / Contrast / Gamma / Saturation / Sharpness / Light
+/-       adjust selected value in live mode; scale ROI in review mode
1/2/3/0   Pins / Text / Damage / Reset presets
C         capture current frame and enter ROI review
O         toggle detection boxes
I         toggle board-side input-adjust sync
A/D/W/S   move ROI in review mode
Enter     accept ROI
Delete/N  mark negative
Q/Esc     quit
```

`Prefix` controls the file stem. Keep it as `chip` for normal positives; use `neg` before capturing negative samples if you want the filenames to visually separate them. The label status still comes from `Accept` or `Negative`.

# Chip Capture GUI

Run from the project root:

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui
```

The default PC GUI is PyQt5 based and keeps using the ADB backend. It is now
focused on mask-first defect observation and CVAT segmentation sample capture
from Windows.

Board-local HDMI interface:

```bash
cd /userdata/chipcheck_vision
/usr/bin/python3 -m tools.chip_capture_gui --board-ui --backend local --profile chip-two-stage-obb-seg-imx678 --screen-width 800 --screen-height 600 --fullscreen
```

The board-local backend starts the stream binary directly on TaishanPi and does
not use ADB `exec-out` for frames.

Board-local Qt interface for the TaishanPi 3M HDMI LCD:

```bash
cd /userdata/chipcheck_vision
/usr/bin/python3 -m tools.chip_capture_gui --board-ui --backend local --screen-width 800 --screen-height 600 --fullscreen
```

In board UI mode the live preview owns the full `800x600` surface. The right
toolbar starts collapsed as a small square button; clicking it opens a
semi-transparent floating control panel over the preview instead of shrinking
the camera image.

The installed desktop launcher is:

```text
/usr/local/bin/chipcheck-qt-gui
/home/lckfb/Desktop/chipcheck-qt.desktop
/usr/share/applications/chipcheck-qt.desktop
```

The Qt board launcher uses Debian system Python and expects PyQt5 plus cv2 for
frame conversion/rendering:

```bash
apt-get install -y python3-pyqt5 python3-opencv python3-numpy
```

Default live stream:

```text
chip-two-stage-obb-seg-imx678
chip_conf=0.45
defect_conf=0.45
defect_confirm=3
display_max_defects=20
overlay=mask-contour
chip_interval=1
roi_smooth_alpha=0.55
roi_hold=1
```

This is equivalent to the current command-line live view:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-obb-seg-imx678 --conf 0.25 --chip-conf 0.45 --defect-conf 0.45 --defect-confirm 3 --display-max-defects 20 --overlay-mode mask-contour --chip-interval 1 --roi-smooth-alpha 0.55 --roi-hold 1
```

The Qt GUI profile selector can still choose the older
`chip-two-stage-seg-imx678` HBB profile for comparison, but current calibration
capture defaults to `chip-two-stage-obb-seg-imx678`. The OBB profile uses the
same board binary with `model/chip_roi_yolov8_obb_split_int8.rknn`,
`defect_model_kind=seg`, and `overlay=mask-contour`; PC drawing accepts either
an explicit OBB sidecar (`Detection.obb_points` plus optional
`Detection.obb_angle`) or a 4-point `chip` contour and renders that as the
chip-only rotated box. Defect classes continue to use mask/contour overlays
without defect bboxes.

The GUI additionally refines the displayed/saved chip OBB from the clean camera
image: the RKNN chip result supplies the coarse chip region, then OpenCV
thresholding plus `minAreaRect` snaps the rotated rectangle to the visible chip
body and pins. This is a GUI-side capture aid; the board still runs the RKNN
two-stage stream for chip/defect inference.

For angle-sensitive OBB capture, choosing `chip-two-stage-obb-seg-imx678`
automatically applies the balanced chip ROI preset:

```text
chip_conf=0.45
chip_interval=1
roi_smooth_alpha=0.55
roi_hold=1
```

Launch Qt GUI collection with the preset:

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui --profile chip-two-stage-obb-seg-imx678 --output-dir .\chip_seg\captures\obb_angle_refine_YYYYMMDD
```

The preset can be overridden with `--chip-conf`, `--chip-interval`,
`--roi-smooth-alpha`, and `--roi-hold` when a specific capture session needs a
different stability/response trade-off.

Segmentation CVAT samples saved from the GUI use a separate session folder:

```text
chip_seg/captures/gui_session_YYYYMMDD_HHMMSS/
  images/seg_0001.jpg
  labels/seg_0001.txt
  images_full/seg_0001.jpg
  previews/seg_0001.jpg
  meta/seg_0001.json
  manifest.csv
```

Workflow:

1. Start camera.
2. Keep `Use segmentation defect model` and `Mask / contour overlay` enabled.
3. Tune light or Advanced sliders only when the visible mask is unstable.
4. Change the physical chip sample or defect state.
5. Click `Save Seg Sample` once for each stable state.

For defect segmentation CVAT collection, keep the live view running, change the
physical chip sample, then click `Save Seg Sample` once. It saves the latest
clean frame's chip ROI, current model YOLO-seg prelabels, full frame, preview,
metadata, and manifest row. If no chip ROI is detected, nothing is saved. This
manual GUI path is recommended when a person is changing samples; the automatic
`seg_cvat_pipeline.py capture` command is only appropriate when the scene keeps
changing by itself, such as a feeder or conveyor.

For quick visual records, click `Save Photo Pair` or press `P`. This saves the
latest full-frame original and a freshly drawn marked image as a paired snapshot:

```text
snapshots/original/photo_YYYYMMDD_HHMMSS_mmm_f000001_original.jpg
snapshots/marked/photo_YYYYMMDD_HHMMSS_mmm_f000001_marked.jpg
snapshots/manifest.csv
```

The original image uses the latest clean camera frame. The marked image is drawn
from the same frame with the current display adjustment and active mask/contour
overlay settings, independent of whether `Show original frame` is currently
checked.

Current view defaults:

```text
Light 50%
High Light 20%
Low Light 20%
Back Light 20%
Brightness -6
Contrast 1.28
Gamma 0.91
Saturation 0.30
Sharpness 0.85
Denoise 6
```

The current independent WS2812-256 backlight default is DI on `GPIO3_A2`,
which corresponds to the TaishanPi 40-pin physical pin 38.

`Sync view to NPU input` is enabled by default. With the default two-stage MaixCAM stream, Brightness/Contrast/Gamma/Saturation/Sharpness are written to the board-side `/tmp/chip_input_adjust.conf`, so the live frame shown by the GUI matches the RGB888 frame used by chip ROI and defect RKNN inference.

Denoise and CLAHE are not sent to the board-side NPU input. Denoise remains a GUI observation/capture option only; the old NLM denoise path was too slow for 1280x720 realtime preview and could make the GUI appear frozen while the slider was being dragged.

The simplified PyQt toolbar no longer exposes the earlier ROI label/review
buttons or defect-box display toggles. The segmentation capture path still uses
the latest chip ROI internally so cropped CVAT samples keep the same geometry.
The live display keeps one bbox overlay for the `chip` class only, as a chip ROI
reference; defect classes remain mask/contour overlays without defect bboxes.

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
Start/Stop        camera stream
Save Seg Sample   save one CVAT segmentation sample
Save Photo Pair   save paired original and marked full-frame snapshots
S/Enter           keyboard shortcut for Save Seg Sample
P                 keyboard shortcut for Save Photo Pair
Q/Esc             close the Qt GUI
Advanced          image tuning sliders and presets
Right arrow tab   board UI floating toolbar open/close
```

Segmentation live mode separates overlay controls:

```text
Mask / contour overlay  default on for seg
Use segmentation model   default on
Profile selector         includes IMX678 OBB seg, default stays IMX678 seg
```

The command-line live view exposes the same behavior through `--overlay-mode`.
Seg profiles default to `mask-contour`, with the same chip-only bbox reference.

The side panel loads the catgirl background asset from:

```text
tools/chip_capture_gui/assets/neko_assistant.png
```

If that file is absent, it falls back to the bundled `neko_assistant.svg`.

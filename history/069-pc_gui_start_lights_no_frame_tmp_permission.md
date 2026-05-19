# PC Qt GUI Start lights on but no frame due to /tmp protected_regular

Updated: 2026-05-13

## Symptom

When launching the PC PyQt GUI with the ADB backend and clicking `Start`, the
WS2812 lights turned on but the preview stayed blank.

The same default profile reproduced in headless mode:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-obb-seg-imx678 --frames 3 --headless
```

Initial failure:

```text
Runtime setup: WS2812=ok rgb=190,255,100 brightness=0.50/0.20/0.20 backlight=0.20@GPIO3_A2/256 (ok)
Protocol error: bad magic: expected b'RYL1', got b'sh: '
Processed frames: 0
```

The `sh: ` bytes came from remote shell errors polluting the binary frame
stream before the expected `RYL1` frame magic.

## Root cause

The default runtime files were under `/tmp`:

- `/tmp/chip_input_adjust.conf`
- `/tmp/rknn_yolo11_camera_stream.log`

On the board, `/proc/sys/fs/protected_regular` is `2`. In sticky world-writable
directories like `/tmp`, this can reject redirection/open attempts against a
regular file owned by another user, even when mode bits look permissive.

Observed stale files:

```text
/tmp/chip_input_adjust.conf       lckfb:lckfb or root:root depending on last launcher
/tmp/rknn_yolo11_camera_stream.log lckfb:lckfb
```

When ADB root or the `lckfb` desktop launcher crossed ownership, shell
redirection such as `2>/tmp/rknn_yolo11_camera_stream.log` could fail with
`cannot create ... Permission denied`, and the error appeared on stdout where
the PC expected the binary video protocol.

## Fix

Moved defaults out of `/tmp` into the writable non-sticky runtime directory:

```text
/userdata/rknn_yolo11_demo/rknn_yolo11_camera_stream.log
/userdata/rknn_yolo11_demo/chip_input_adjust.conf
```

Changed files:

- `tools/adb_imx415_rknn_live_view.py`
  - `DEFAULT_REMOTE_LOG`
  - `DEFAULT_INPUT_ADJUST_FILE`
  - ADB input-adjust writer now removes/recreates the file before writing.
  - Remote stream command removes/recreates the log before redirecting stderr.
- `tools/chip_capture_gui/settings.py`
  - `CameraSettings.input_adjust_file` now uses `DEFAULT_INPUT_ADJUST_FILE`.
- `tools/chip_capture_gui/camera.py`
  - GUI input-adjust writer removes/recreates the file before writing.

The updated files were also pushed to the board Qt GUI project:

```text
/userdata/chipcheck_vision/tools/adb_imx415_rknn_live_view.py
/userdata/chipcheck_vision/tools/chip_capture_gui/settings.py
/userdata/chipcheck_vision/tools/chip_capture_gui/camera.py
```

## Verification

Local compile:

```powershell
python -m py_compile .\tools\adb_imx415_rknn_live_view.py .\tools\chip_capture_gui\settings.py .\tools\chip_capture_gui\camera.py .\tools\chip_capture_gui\app.py
```

Headless smoke after the fix:

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --profile chip-two-stage-obb-seg-imx678 --frames 3 --headless --save-clean-snapshot .\captures\gui_start_diag_clean_runtime_dir.jpg --save-snapshot .\captures\gui_start_diag_annotated_runtime_dir.jpg
```

Result:

```text
Runtime setup: WS2812=ok rgb=190,255,100 brightness=0.50/0.20/0.20 backlight=0.20@GPIO3_A2/256 (ok)
frame=0 fps=0.0 focus=63 size=1280x720 det=1/1
Processed frames: 3
Saved snapshot: captures\gui_start_diag_annotated_runtime_dir.jpg
Saved clean snapshot: captures\gui_start_diag_clean_runtime_dir.jpg
```

Board Qt compile/import check:

```text
remote_log=/userdata/rknn_yolo11_demo/rknn_yolo11_camera_stream.log
input_adjust_file=/userdata/rknn_yolo11_demo/chip_input_adjust.conf
```

## Residual notes

- If an already-open PC GUI was started before this fix, close and restart it so
  it imports the updated defaults.
- This fix addresses the blank preview caused by shell redirection errors. It
  does not change camera/model behavior.

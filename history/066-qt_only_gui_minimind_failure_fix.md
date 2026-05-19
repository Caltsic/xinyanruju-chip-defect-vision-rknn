# 066 - Qt-only GUI / MiniMind failure handling archive

## User Requirement

- User explicitly requested to ignore the OpenCV GUI path and focus on Qt.
- OpenCV GUI software should be removed from the active workflow.
- The immediate field issue was that MiniMind generation failed during Qt GUI testing.
- This archive records the current round state only; business code should not be changed by the archive-only follow-up.

## Local Changes Recorded For This Round

- Removed the OpenCV GUI implementation file:
  - `tools/chip_capture_gui/opencv_app.py`
- Changed the GUI module entrypoint:
  - `tools/chip_capture_gui/__main__.py`
  - `--opencv` now fails explicitly with a clear error.
  - Normal startup imports and launches the Qt GUI only.
- Changed board desktop launchers to Qt board UI:
  - `board/desktop/chipcheck-hdmi-gui`
  - `board/desktop/chipcheck-qt-gui`
  - Both launch via `/usr/bin/python3` to use the board system PyQt environment.
  - Both pass Qt `--board-ui`.
  - Both pass an explicit MiniMind-O voice command.
  - Voice command timeout is set to `360` seconds.
- Updated voice assistant defaults:
  - `tools/chip_capture_gui/voice_assistant.py`
  - Default playback device changed to `plughw:0,0` for TaishanPi local audio output.
  - Added default MiniMind-O command discovery for the deployed board paths.
  - When MiniMind generation fails, the Qt green overlay should show a `MiniMind failed` style failure message instead of silently disappearing.
- Updated Qt GUI voice display behavior:
  - `tools/chip_capture_gui/app.py`
  - Added green streaming text overlay in the Qt preview area.
  - Added support for displaying voice assistant streaming/result text on Qt, not only OpenCV.
  - Voice timeout default adjusted to `360` seconds.
- Updated README usage notes:
  - Removed OpenCV GUI launch commands so the documented operator path is Qt-only.

## Verification Recorded

- Python compile check passed with `py_compile`.
- Desktop shell launcher syntax checks passed with `bash -n`.
- Local `--opencv` launch test now returns the expected explicit error.
- `rg` check found only the deliberate `--opencv` error path remaining, not active OpenCV GUI launch commands.

## Blocker / Not Completed On Board

- Windows ADB device list was empty during this round.
- Because ADB was disconnected, the following board-side actions could not be completed:
  - Push the Qt-only launcher/code changes to the board.
  - Delete remote `/userdata/chipcheck_vision/tools/chip_capture_gui/opencv_app.py`.
  - Restart the board Qt GUI.
  - Read the MiniMind failure logs from the board.
- Treat the Qt-only MiniMind fix as local-prepared but not board-deployed until ADB is restored and a board smoke test is run.

## Recovery Point For Next Agent

When ADB is restored, continue from board deployment and verification only:

1. Push the changed local files to `/userdata/chipcheck_vision/`.
2. Remove the remote OpenCV GUI file if present.
3. Restart the board desktop launcher and confirm the process uses `/usr/bin/python3 -m tools.chip_capture_gui --board-ui`.
4. Trigger a Qt voice request and inspect:
   - `/userdata/chipcheck_vision/voice_assistant/last_result.json`
   - `/userdata/chipcheck_vision/voice_assistant/assistant_command.log`
   - `/tmp/chipcheck-hdmi-gui.log`
5. Confirm the green Qt overlay shows either the streaming MiniMind reply or an explicit failure message.

## Keywords

Qt-only, OpenCV GUI removed, MiniMind failed overlay, voice timeout, 360s, ADB disconnected, board-ui, `/usr/bin/python3`, `plughw:0,0`

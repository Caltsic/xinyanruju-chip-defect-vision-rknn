# 067 - MiniMind Qt Illegal Instruction And EAGET Mount Fix Archive

## Scope

- This archive records the board deployment and MiniMind-O repair completed after the user restored power and ADB.
- ADB device `2e2609c37dc21c0a` recovered.
- Work was limited to recording the round outcome for history reuse.

## Initial Board State

- Old board logs showed `assistant_command.log` reached an `onnxruntime` warning and then failed with `Illegal instruction`.
- The previous round had prepared Qt-only MiniMind changes locally but board verification was blocked by disconnected ADB.

## Board Deployment Completed

- Synced these files to the board:
  - `tools/chip_capture_gui/__main__.py`
  - `tools/chip_capture_gui/app.py`
  - `tools/chip_capture_gui/voice_assistant.py`
  - `tools/minimind_o_voice_runner.py`
  - `board/desktop/chipcheck-hdmi-gui`
  - `board/desktop/chipcheck-qt-gui`
- Removed remote OpenCV GUI implementation:
  - `/userdata/chipcheck_vision/tools/chip_capture_gui/opencv_app.py`
- Board `--opencv` smoke returned `rc=1` with the expected `OpenCV GUI removed` error.
- Qt process launched as:
  - `/usr/bin/python3 -m tools.chip_capture_gui --board-ui ... --voice-command ...`

## EAGET Mount Recovery

- After power loss, EAGET was not mounted.
- `/dev/mmcblk1p1` was identified as the `vfat` `EAGET` partition.
- Mounting it at `/mnt/eaget` restored the deployed repo and MiniMind resources.
- Added EAGET automount handling to both desktop launchers:
  - `board/desktop/chipcheck-hdmi-gui`
  - `board/desktop/chipcheck-qt-gui`

## Illegal Instruction Root Cause

- Standalone `funasr` import returned `rc=132`.
- `PYTHONFAULTHANDLER` located the `Illegal instruction` during import of:
  - `funasr/models/bicif_paraformer/cif_predictor.py`
- The failing path was `torch.jit.script` execution during `funasr` import.
- A test monkey patch that replaced `torch.jit.script` with a passthrough allowed `funasr` import to succeed.

## Fix Recorded

- Added `_disable_torch_jit_script` in:
  - `tools/minimind_o_voice_runner.py`
- Called the patch before `run` / `_load_model` imports the MiniMind/FunASR stack.
- This prevents the board CPU from hitting the unsupported instruction path in Torch JIT scripting while keeping the rest of MiniMind-O loading intact.

## Verification

- Text smoke:
  - `4` tokens
  - `rc=0`
  - `elapsed=51.258s`
- Audio smoke:
  - `4` tokens
  - `rc=0`
  - `elapsed=56.981s`
  - Streaming text was produced.
  - Result still used fallback tone in this short run.
- Audio smoke:
  - `12` tokens
  - `rc=0`
  - `elapsed=58.788s`
  - `reply_text`: `好的，请问您需要什么样的诗歌？比如`
  - `audio_frames=4`
  - `audio_decoded=true`
  - `fallback_tone=false`
- Playback verification:
  - `aplay -D plughw:0,0 reply.wav`
  - `rc=0`

## Final State

- After restarting Qt, EAGET automount worked.
- Qt process remained stable.
- MiniMind-O no longer failed at the previous `funasr` / `torch.jit.script` `Illegal instruction` point.
- Audio decode and local speaker playback were verified through `plughw:0,0`.

## Keywords

MiniMind-O, Qt, Illegal instruction, funasr, torch.jit.script, EAGET automount, audio_decoded, plughw:0,0, ADB, `2e2609c37dc21c0a`, `/mnt/eaget`, `/dev/mmcblk1p1`

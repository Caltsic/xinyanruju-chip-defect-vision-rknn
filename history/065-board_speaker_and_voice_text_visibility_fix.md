# 扬声器切到泰山派本机输出与 PyQt 文字浮层修复

## 用户反馈

- 三段 WS2812 灯光表现正常。
- MiniMind-O 回复文字没有看到。
- 希望扬声器改用泰山派本机输出。

## 排查发现

- 板端 `aplay -l` 显示 `card0` 是 `rockchip-es8388`，`card1` 是 HDMI。
- 原默认播放设备是 `plughw:1,0`，实际指向 HDMI；应改为泰山派本机 codec：`plughw:0,0`。
- `last_result.json` 显示 `mode: placeholder`，说明当时运行的 GUI 没有带 MiniMind-O `--voice-command`，只跑了占位回复。
- `ps` 显示当前实际运行的是 PyQt 入口：`python3 -m tools.chip_capture_gui --board-ui ...`，不是上一轮主要修改的 OpenCV 入口，所以绿色 OpenCV overlay 不会显示。

## 修复文件

- `tools/chip_capture_gui/voice_assistant.py`
  - 默认 playback 改为 `plughw:0,0`。
  - 新增 `default_minimind_command()`。
  - 本地/板端 enabled 且未传 command 时，自动补 MiniMind-O runner。
- `tools/chip_capture_gui/app.py`
  - PyQt 新增 `QTextEdit#voiceReplyOverlay` 左上绿色浮层。
  - 250ms 刷新，TTL 自动消失，可滚动。
  - CLI playback 默认改为 `plughw:0,0`。
- `tools/chip_capture_gui/opencv_app.py`
  - playback 默认改为 `plughw:0,0`。
- `board/desktop/chipcheck-hdmi-gui`
  - `pgrep` 从只查 OpenCV 改为查所有 `python3 -m tools.chip_capture_gui`，避免重复启动 GUI。

## 验证

- 本地 `py_compile` 通过。
- 推到板端后，`/usr/bin/python3` 和 miniforge 环境的 `py_compile` 均通过。
- 板端测试 `VoiceAssistantController(VoiceAssistantSettings(enabled=True))`，得到 playback 为 `plughw:0,0`，且 `has_command True`。
- PyQt offscreen 测试 `voice_overlay.isVisible() True`，文本为“绿色回复浮层测试...”。
- `aplay -D plughw:0,0 ...reply.wav` 播放成功。
- 当前已重启为 OpenCV 实时入口，`ps` 显示 `chip_capture_gui --opencv ... --voice-command ... --stream-text ...` 和 `rknn_chip_two_stage_maixcam_stream` 均在运行。

## 注意

- 本轮没有修改三段灯光逻辑。
- 灯光已恢复默认 `0.50/0.20/0.20`。
- 如果用户用 PyQt `--board-ui` 手动入口，也会自动补 command 并显示文字。
- 如果用 OpenCV 桌面入口，也有文字 overlay。
- MiniMind-O 加载仍然有约一分钟 CPU 延迟，文字会在 runner 开始生成后出现。

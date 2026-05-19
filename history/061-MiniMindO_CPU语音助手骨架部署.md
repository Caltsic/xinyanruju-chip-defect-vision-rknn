# MiniMind-O CPU-only 语音助手骨架部署

日期：2026-05-12

## 目标

在不影响当前芯片缺陷检测主链路的前提下，为泰山派 3M / RK3576 板端 GUI 增加一个按键式本地语音助手入口：

```text
GUI 开始录音 -> GUI 停止录音 -> CPU-only 语音理解/推理 -> GUI 显示文本结果 -> HDMI/声卡播放回答音频
```

本轮完成的是非侵入式语音助手骨架部署和音频闭环，不是完整 MiniMind-O 实模型安装。

## 非干扰边界

- 不修改当前 RKNN 检测模型。
- 不修改当前检测二进制默认推理路径。
- MiniMind-O / 语音助手不使用 NPU，避免和 chip OBB + defect seg 检测抢 NPU。
- 不开机自启语音助手。
- 不常驻连续监听。
- 不做双工、barge-in 打断或视觉输入给 MiniMind-O。
- GUI 主线程、CameraThread 和 OpenCV 主循环不执行 STT/LLM/TTS 重计算。
- `/userdata` 只放脚本、小 WAV 和结果 JSON；不放大模型权重。
- 实模型接入时通过 `--voice-command` 调用独立 Python 3.10 环境脚本，避免污染现有板端 Python 3.13 检测 GUI 环境。

## MiniMind-O 上游事实

已查 MiniMind-O 官方上游信息：

- 上游仓库：<https://github.com/jingyaogong/minimind-o>
- 技术报告：<https://arxiv.org/abs/2605.03937>
- `minimind-3o` 主干约 `0.1B`，2026-05-05 发布说明中为 `115M` 级。
- `minimind-3o-moe` 为约 `0.3B-A0.1B`。
- MiniMind-O 的 `0.1B` 口径主要指 Thinker、Talker 和 projector 等可训练主体；完整 Omni 运行还会加载冻结的 SenseVoice-Small、SigLIP2、Mimi、CAM++ 等旁路组件。
- 完整语音进语音出链路依赖 PyTorch、Transformers、FunASR、ONNX Runtime、Mimi/SenseVoice 等组件，不能按“只有 0.1B 文本小模型”估算资源。

当前板端尚未安装 MiniMind-O 实模型：

- 未安装 MiniMind-O 的 PyTorch / FunASR / Mimi / SenseVoice 等完整依赖。
- 未下载 MiniMind-O 权重。
- 当前默认 `--voice-command` 为空，语音助手执行安全占位流程：保存录音、写 `last_result.json`、生成短提示音 `last_reply.wav`，再通过 `aplay` 播放。
- 后续接入实模型时，外部命令通过 `{input_wav}`、`{reply_wav}`、`{result_json}`、`{work_dir}` 占位符对接。

## 板端音频与系统事实

板端已确认存在 ALSA 音频设备和命令：

```text
card0: rockchip-es8388
card1: rockchip-hdmi
card2: rockchip-dp0
/usr/bin/arecord
/usr/bin/aplay
```

板端主 Python 记录为：

```text
/srv/rk3576-storage/miniforge/bin/python3
Python 3.13.12
```

音频闭环结果：

```bash
arecord -D hw:0,0 -f S16_LE -r 16000 -c 1 -d 1 /userdata/chipcheck_vision/voice_assistant/audio_probe.wav
```

结果：录音成功，输出约 `32KB` 的 `audio_probe.wav`。

```bash
aplay -D hw:1,0 /userdata/chipcheck_vision/voice_assistant/audio_probe.wav
```

结果：HDMI 直连设备播放失败，错误为 `Channels count non available`。

```bash
aplay -D plughw:1,0 /userdata/chipcheck_vision/voice_assistant/audio_probe.wav
```

结果：播放成功。后续 HDMI 输出默认使用 `plughw:1,0`。

## 代码改动

新增：

```text
tools/chip_capture_gui/voice_assistant.py
```

核心类：

- `VoiceAssistantSettings`
- `VoiceAssistantController`

主要行为：

- 使用 `arecord` 保存 `last_input.wav`。
- 使用 `aplay` 播放 `last_reply.wav`。
- `assistant_command` 为空时走占位模式，生成 `last_result.json` 和短提示音。
- `assistant_command` 非空时用 shell 命令执行外部 MiniMind-O / ASR / TTS 脚本。
- 通过 `OMP_NUM_THREADS`、`OPENBLAS_NUM_THREADS`、`MKL_NUM_THREADS`、`NUMEXPR_NUM_THREADS` 限制外部命令线程数，默认 `max_threads=2`。
- 录音、占位推理、播放都在后台线程/子进程中执行，不阻塞 GUI 检测主链路。
- `shutdown()` 会停止录音进程、关闭日志、等待后台 worker 退出。

PyQt GUI 接入：

```text
tools/chip_capture_gui/app.py
```

改动点：

- 引入 `VoiceAssistantController` / `VoiceAssistantSettings`。
- 新增 `Voice` 区域：`Start Mic`、`Stop Mic`、`Replay`、状态文本。
- 使用 `pyqtSignal(str)` 把后台语音状态切回主线程更新 UI。
- 快捷键接入 `toggle_recording()`。
- `shutdown()` 中调用 `voice_controller.shutdown()`。
- 新增 CLI 参数：

```text
--voice-assistant
--no-voice-assistant
--voice-command
--voice-workdir
--voice-record-device
--voice-playback-device
--voice-threads
```

OpenCV GUI 接入：

```text
tools/chip_capture_gui/opencv_app.py
```

改动点：

- 引入同一个 `VoiceAssistantController`。
- `M` 键开始/停止录音。
- `B` 键重播最近一次回答。
- HUD 增加 `M mic`、`B replay` 和 `mic=<status>`。
- `finally` 中调用 `voice_controller.shutdown()`，与 `camera.stop()`、补光关闭、`cv2.destroyAllWindows()` 同级清理。
- 新增与 PyQt 同名的 `--voice-*` 参数。

## 板端部署路径

本轮已同步到板端：

```text
/userdata/chipcheck_vision/tools/chip_capture_gui/voice_assistant.py
/userdata/chipcheck_vision/tools/chip_capture_gui/app.py
/userdata/chipcheck_vision/tools/chip_capture_gui/opencv_app.py
/userdata/chipcheck_vision/voice_assistant/
```

默认工作文件：

```text
/userdata/chipcheck_vision/voice_assistant/last_input.wav
/userdata/chipcheck_vision/voice_assistant/last_reply.wav
/userdata/chipcheck_vision/voice_assistant/last_result.json
/userdata/chipcheck_vision/voice_assistant/arecord.log
/userdata/chipcheck_vision/voice_assistant/aplay.log
/userdata/chipcheck_vision/voice_assistant/assistant_command.log
```

## 验证命令和结果

板端占位链路验证输出：

```text
voice recording
voice thinking
voice done
input_exists=True
reply_exists=True
result_exists=True
```

板端 GUI 参数验证：

```bash
cd /userdata/chipcheck_vision
python3 -m tools.chip_capture_gui --opencv --backend local --help
```

结果：帮助信息已显示 `--voice-*` 参数。

板端语法检查：

```text
compile(...) passed:
tools/chip_capture_gui/voice_assistant.py
tools/chip_capture_gui/app.py
tools/chip_capture_gui/opencv_app.py
```

非干扰验证：

```text
Baseline: 80 frames, about 6.1-6.4 FPS after warmup
Concurrent voice placeholder: 100 frames, about 6.3-6.7 FPS after warmup
Processed frames: 100
```

结论：当前占位语音助手不会打断芯片检测，也未观察到持续 FPS 下滑。该结果只证明音频采集、占位推理和播放骨架不干扰检测；不代表完整 MiniMind-O ASR/LLM/TTS 实模型已经验证。

本地归档时补充复核：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; @'
from pathlib import Path
for rel in [
    'tools/chip_capture_gui/voice_assistant.py',
    'tools/chip_capture_gui/app.py',
    'tools/chip_capture_gui/opencv_app.py',
]:
    path = Path(rel)
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
    print(f'compile ok: {rel}')
'@ | F:\anaconda\python.exe -
```

结果：

```text
compile ok: tools/chip_capture_gui/voice_assistant.py
compile ok: tools/chip_capture_gui/app.py
compile ok: tools/chip_capture_gui/opencv_app.py
```

本地 CLI 参数复核：

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui --opencv --backend local --help | Select-String -Pattern '--voice|M mic|B replay'
```

结果：帮助信息显示 `--voice-assistant`、`--no-voice-assistant`、`--voice-command`、`--voice-workdir`、`--voice-record-device`、`--voice-playback-device`、`--voice-threads`。

本地只读 ADB 路径复核尝试：

```powershell
adb devices
adb shell "ls -l /userdata/chipcheck_vision/tools/chip_capture_gui/voice_assistant.py /userdata/chipcheck_vision/tools/chip_capture_gui/app.py /userdata/chipcheck_vision/tools/chip_capture_gui/opencv_app.py /userdata/chipcheck_vision/voice_assistant 2>/dev/null"
```

结果：当前 PowerShell 环境中 `adb` 不在 PATH，命令未执行到板端；未对板端做任何修改。板端部署事实以上述 `progress.md` 中完成记录为准。

## 使用入口

板端 OpenCV GUI：

```bash
cd /userdata/chipcheck_vision
python3 -m tools.chip_capture_gui --opencv --backend local --fullscreen
```

OpenCV 快捷键：

```text
M: start/stop mic
B: replay latest reply
```

PC/ADB Qt GUI 可使用同一组 `--voice-*` 参数，但语音助手默认只在 `backend=local` 或 board UI 场景启用。

## 剩余风险

- 完整 MiniMind-O 实模型未安装、未测速；当前验证只覆盖占位链路。
- 完整 Omni 链路会加载冻结外部模块，CPU 和内存压力显著高于 0.1B 主干数字。
- 板端现有 Python 3.13 与 MiniMind-O 官方参考 Python 3.10 不一致，不能直接把依赖安装进现有检测 GUI 环境。
- ASR/TTS 接入后可能出现 CPU 峰值、播放延迟或 GUI FPS 波动，需要重新做 100/300 帧并发验证。
- HDMI 音频使用 `plughw:1,0` 才通过；现场若换显示器/声卡，应先重新跑 `arecord/aplay` 闭环。
- 如果后续 `--voice-command` 生成的 `last_reply.wav` 采样率/声道不兼容 HDMI，应由外部命令或 `aplay` 前处理统一格式。

## 下一步

1. 单独创建 MiniMind-O Python 3.10 环境，不污染 `/srv/rk3576-storage/miniforge/bin/python3`。
2. 先接最小文本/占位命令，继续使用 `--voice-command` 输出 `result_json` 和 `reply_wav`。
3. 再接 ASR，验证短语音输入到文本的耗时和检测 FPS。
4. 最后接 TTS 或 MiniMind-O Talker/Mimi 输出，验证播放期间检测稳定性。
5. 每接入一个真实模型阶段，都重新记录 CPU、内存、FPS、音频成功率和 GUI 退出清理状态。

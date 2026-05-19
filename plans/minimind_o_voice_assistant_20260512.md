# MiniMind-O 板端语音助手部署计划

更新时间：2026-05-12

## 目标

在不影响现有芯片检测主链路的前提下，给泰山派 3M / RK3576 板端 GUI 增加一个按键式语音助手入口：

```text
GUI 开始录音 -> GUI 停止录音 -> CPU-only 语音理解/推理 -> GUI 显示文本结果 -> HDMI/声卡播放回答音频
```

## 不变更边界

- 不修改当前 RKNN 检测模型。
- 不修改当前板端检测二进制的默认推理路径。
- 不让 MiniMind-O 或音频助手使用 NPU。
- 不开机自启语音助手。
- 不常驻连续语音监听。
- 不做双工、打断、视觉输入给 MiniMind-O。
- 不把大模型文件放入 `/userdata`。

## 当前依据

板端实测：

```text
MemTotal:      about 3.8 GiB
MemAvailable: about 3.4 GiB
Root FS free:  about 11 GiB
/userdata free: about 545 MiB
Audio devices: ES8388, HDMI, DP
Tools: arecord, aplay
Current OBB + segmentation chain: about 6.3-6.7 FPS in strict per-frame OBB+Seg smoke
```

MiniMind-O 上游事实：

- `minimind-3o` 主干约 `0.1B`，发布说明中为 `115M`。
- 完整 Omni 链路依赖 SenseVoice-Small、SigLIP2、Mimi、CAMPPlus、Transformers、FunASR、ONNX Runtime、PyTorch 等。
- 官方参考环境为 Python 3.10；当前板端主 Python 是 3.13，因此完整依赖不应直接污染现有环境。

## 分阶段实施

| 阶段 | 状态 | 内容 |
|---|---|---|
| 1. 规划落盘 | complete | 明确不影响检测的边界、部署目录、验证标准 |
| 2. 音频硬件闭环 | complete | `arecord hw:0,0` 录音成功，`aplay plughw:1,0` HDMI 播放成功 |
| 3. CPU-only 助手骨架 | complete | 新增独立 Python 模块，负责录音、调用推理命令、播放音频 |
| 4. GUI 接入 | complete | PyQt 增加按钮，OpenCV 增加快捷键，所有推理在后台线程/子进程执行 |
| 5. 板端部署 | complete | 已同步到 `/userdata/chipcheck_vision`，未改检测二进制 |
| 6. 非干扰验证 | complete | 检测 100 帧期间并发录音/占位推理/播放，视觉链路未中断 |
| 7. MiniMind-O 实模型接入 | pending | 另建 Python 3.10/独立目录，先文本/占位，再接 ASR/TTS |

## 施工设计

新增模块：

```text
tools/chip_capture_gui/voice_assistant.py
```

职责：

- `VoiceAssistantController`
  - 管理录音进程、后台推理线程、播放进程。
  - 默认低优先级运行，不阻塞 GUI 主线程。
  - 使用 `arecord` 保存 WAV。
  - 使用 `aplay` 播放 WAV。
  - 推理命令可配置；未配置 MiniMind-O 时走安全占位模式。
- `VoiceAssistantSettings`
  - `enabled`
  - `record_device`
  - `playback_device`
  - `sample_rate`
  - `channels`
  - `assistant_command`
  - `work_dir`

默认板端目录：

```text
/userdata/chipcheck_vision/voice_assistant/
```

默认音频文件：

```text
/userdata/chipcheck_vision/voice_assistant/last_input.wav
/userdata/chipcheck_vision/voice_assistant/last_reply.wav
/userdata/chipcheck_vision/voice_assistant/last_result.json
```

默认策略：

- `assistant_command` 为空时，保存录音并生成短促提示音/占位结果，证明 GUI、录音、播放链路已通。
- 接入 MiniMind-O 时，命令读取输入 WAV，输出 JSON 和回复 WAV。
- 命令通过 `nice -n 10`、`taskset` 或脚本内部限线程运行。

## GUI 交互

PyQt GUI：

- 增加 `Voice` 区域：
  - `Start Voice`
  - `Stop Voice`
  - 状态文本：`Idle / Recording / Thinking / Playing / Error`
- 停止录音后后台执行推理/播放。
- 检测流线程不等待语音助手完成。

OpenCV GUI：

- 快捷键建议：
  - `M`: 开始/停止录音切换。
  - `B`: 播放最近一次回答。
- 状态栏显示简短语音状态。

## 已部署文件

本地：

```text
tools/chip_capture_gui/voice_assistant.py
tools/chip_capture_gui/app.py
tools/chip_capture_gui/opencv_app.py
```

板端：

```text
/userdata/chipcheck_vision/tools/chip_capture_gui/voice_assistant.py
/userdata/chipcheck_vision/tools/chip_capture_gui/app.py
/userdata/chipcheck_vision/tools/chip_capture_gui/opencv_app.py
/userdata/chipcheck_vision/voice_assistant/
```

## 已验证结果

音频闭环：

```text
arecord -D hw:0,0 -f S16_LE -r 16000 -c 1 -d 1 .../audio_probe.wav
aplay -D plughw:1,0 .../audio_probe.wav
```

占位语音链路：

```text
voice recording
voice thinking
voice done
last_input.wav exists
last_reply.wav exists
last_result.json exists
```

非干扰检测验证：

```text
Baseline: 80 frames, about 6.1-6.4 FPS after warmup
Concurrent voice placeholder: 100 frames, about 6.3-6.7 FPS after warmup
Processed frames: 100
```

## 验证标准

必须通过：

1. 未启用语音助手时，现有 GUI 和实时检测命令行为不变。
2. 录音期间检测画面不中断。
3. 播放期间检测画面不中断。
4. 占位推理期间检测 FPS 不出现持续性大幅下降。
5. 退出 GUI 时能清理 `arecord`、`aplay` 和后台助手进程。

## 风险和缓解

| 风险 | 缓解 |
|---|---|
| MiniMind-O 完整依赖不适配 Python 3.13/aarch64 | 独立 Python 3.10 环境，先不污染现有板端 Python |
| 语音模型 CPU 推理拖慢 GUI | 后台线程/子进程 + nice/taskset + 不常驻 |
| 音频设备占用或无 HDMI 声音 | 配置化 `arecord/aplay -D` 设备，先用硬件闭环确认 |
| 生成语音耗时过长 | 第一版允许推理后一次性播放，不做流式 |
| 大模型文件占满 `/userdata` | 模型放根分区或外置存储，`/userdata` 只放脚本和小 WAV |

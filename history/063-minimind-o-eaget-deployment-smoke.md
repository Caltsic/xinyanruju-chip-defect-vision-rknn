# MiniMind-O EAGET 部署与烟测

日期：2026-05-12

## 目标

本轮在不影响现有芯片视觉检测主链路的前提下，删除已隔离的旧 YOLOv8 环境，挂载 EAGET 作为大文件存储，并尝试把 MiniMind-O 0.1B 语音链路部署到泰山派 3M / RK3576 板端，接入已有 GUI 语音助手入口做最小烟测。

## 旧环境删除

已删除旧隔离目录：

```text
/srv/rk3576-storage/yolov8_env.disabled_20260512
```

结果：

- 删除前大小约 `5.3G`。
- 删除后该旧目录已不存在。
- 释放空间约 `5.3G`。
- 该目录此前已通过改名隔离验证，不属于当前 GUI、RKNN 检测或 MiniMind-O 新环境的运行依赖。

## EAGET 存储状态

EAGET 已挂载：

```text
Device: /dev/mmcblk1p1
Mount:  /mnt/eaget
FS:     vfat / FAT32
Size:   about 117G
Used:   about 2.1G
Free:   about 115G
```

工程判断：

- 适合放模型仓库、权重、下载缓存、数据集、临时产物和推理输出。
- 不适合直接放 Python / conda 环境，因为 vfat/FAT32 对 Linux 权限、软链接、可执行位和大量小文件环境都不友好。
- 如果后续希望把完整 Python 环境也迁到 EAGET，建议先备份数据并改为 ext4。
- 本轮采用的布局是：Python 环境放 eMMC ext4，模型和缓存放 EAGET。

## MiniMind-O 部署布局

仓库路径：

```text
/mnt/eaget/workspace/minimind-o
```

Python 3.10 环境：

```text
/srv/rk3576-storage/minimind_o_env
```

已部署/下载的核心组件和权重：

```text
/mnt/eaget/workspace/minimind-o/model/mimi/model.safetensors
/mnt/eaget/workspace/minimind-o/model/SenseVoiceSmall/model.pt
/mnt/eaget/workspace/minimind-o/out/sft_omni_768.pth
/mnt/eaget/workspace/minimind-o/out/llm_768.pth
```

补充状态：

- dense MiniMind-O 0.1B 语音/文本最小链路所需的 `mimi`、`SenseVoiceSmall`、dense `sft_omni_768.pth`、`llm_768.pth` 已具备。
- 下载过程中曾出现 `llm_768_moe.pth` 等 MoE 文件，但本轮目标使用 dense `sft_omni_768.pth`，MoE 不是本轮最小链路必需项。
- `siglip2-base-p32-256-ve` 尚未作为本轮语音最小链路必需项下载；它主要服务视觉输入链路。
- `campplus` 尚未作为本轮语音最小链路必需项下载；它主要服务说话人嵌入/音色相关链路。

## 依赖与运行注意

Python 环境使用：

```text
Python 3.10
torch 2.6.0 CPU
torchaudio 2.6.0
transformers
onnxruntime
funasr
librosa
soundfile
pydub
snac
speechbrain
modelscope
```

关键问题和处理：

- `funasr` 在该 RK3576 板端环境中直接 import 时可能触发 `Illegal instruction`。
- 规避方式：运行 MiniMind-O / SenseVoice 相关脚本时必须设置 `PYTORCH_JIT=0`。
- `torchaudio` 已固定为 `2.6.0`，用于匹配 `torch 2.6.0`，避免版本错配。
- MiniMind-O 核心 imports 已通过，包括 `model.model_omni`、`OmniConfig`、`OmniDataset` 等。
- `onnxruntime` 可能输出 GPU/DRM 探测 warning，但本轮 CPU-only 路径不依赖 GPU。

推荐运行环境变量：

```bash
export PYTORCH_JIT=0
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export MKL_NUM_THREADS=2
export NUMEXPR_NUM_THREADS=2
```

## GUI 接入改动

本轮 MiniMind-O 真实 runner 接入涉及以下文件：

```text
tools/minimind_o_voice_runner.py
tools/chip_capture_gui/app.py
tools/chip_capture_gui/opencv_app.py
board/desktop/chipcheck-hdmi-gui
```

接入方式：

- GUI 仍通过已有 `--voice-command` 调用外部语音助手命令。
- 外部命令接入 `tools/minimind_o_voice_runner.py`。
- runner 负责读取 GUI 录音文件、调用 MiniMind-O、写回 `result_json` 和 `reply_wav`。
- 桌面脚本 `board/desktop/chipcheck-hdmi-gui` 已配置为走 MiniMind-O runner。
- 桌面脚本默认参数：`max_new_tokens=12`、`timeout=360s`、`threads=2`。
- 该设计保持按键后单次运行，不做双工、不常驻监听，避免长期抢占 CPU。

## 烟测结果

文本输入最小烟测：

```text
max_new_tokens=4
time: about 59s
result: generated text and fallback WAV
```

文本输入带语音解码烟测：

```text
max_new_tokens=12
time: about 57s
audio_frames=4
audio_decoded=true
result: generated real WAV
```

音频样例输入烟测：

```text
max_new_tokens=4
time: about 63s
result: generated text
audio: token 太短，没有产生真实音频帧，生成 fallback WAV
```

板端录音验证：

```text
arecord hw:0,0 1 second: success
```

板端播放验证：

```text
aplay plughw:1,0 WAV: success
```

视觉主链路回归验证：

```text
profile: chip-two-stage-obb-seg-imx678
args: --frames 5 --headless
result: success
```

结论：

- MiniMind-O repo、Python 环境、核心权重和最小 runner 链路已可用。
- 文本输入可产生文本结果。
- 足够 token 时可产生真实语音 WAV。
- 短 token 下不一定有音频帧，runner 会生成 fallback WAV，避免 GUI 播放端失败。
- 视觉检测主链路仍可运行。

## 性能判断

当前板端可用，但非常慢：

- RK3576 CPU 单次 MiniMind-O 问答约 `1` 分钟以上。
- 长回答或完整音频理解链路可能到 `2` 分钟级。
- MiniMind-O 不占 NPU，不会直接抢 RKNN 推理单元。
- 但会吃 CPU 和内存，运行期间可能影响 GUI 响应和采集流畅度。
- 必须按键后单次运行，不做双工，不做常驻监听，不应在检测时频繁触发。

工程结论：

- 当前适合作为“离线演示级/低频辅助问答”。
- 不适合作为实时语音交互助手。
- 如果需要更自然的语音交互，后续应考虑更轻的 ASR/LLM/TTS 拆分方案，或使用外部算力/专门加速路径。

## 当前风险和建议

内存风险：

- 板端约 4GB RAM，无 swap。
- MiniMind-O 运行时峰值可用内存曾低至约 `845MB`。
- 后续下载更多模型或增大 token 时，需关注 OOM、系统卡顿和检测 FPS 波动。

存储风险：

- EAGET 当前为 vfat/FAT32，适合大文件存储，但不适合 Python 环境。
- FAT32 权限和软链接限制可能影响某些包、缓存或工具行为。
- 若 EAGET 未来承载更复杂运行环境，建议改 ext4。

语音链路风险：

- 真实麦克风语义识别还需现场说话测试；当前只确认样例音频和录放音设备链路。
- 短回答 token 不一定产生真实语音帧，需要合理控制 `max_new_tokens`。
- `max_new_tokens` 增大可以提高真实音频输出概率，但会继续增加耗时。
- `funasr` 必须带 `PYTORCH_JIT=0`，否则可能复现 `Illegal instruction`。

GUI 使用建议：

- 检测任务优先时，不要频繁触发语音按钮。
- 触发语音后应等待本次完成，再进行下一次。
- 若现场测试发现检测明显卡顿，可先关闭 `--voice-command` 或恢复占位语音流程。

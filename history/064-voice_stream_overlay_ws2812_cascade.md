# MiniMind-O 绿色流式回复 overlay 与 WS2812 8/12/24 级联三环分段亮度

更新时间：2026-05-12

## 用户需求

本轮目标是在现有 IMX415 视觉 GUI 与 MiniMind-O 语音助手链路上增加两类能力：

1. 模型回复要以绿色文字流式显示在屏幕左上角，一段时间后自动消失；回复过长时允许滚动查看。
2. 补光硬件从旧的单个 WS2812-8 环扩展为三段级联：`WS2812-8 -> WS2812-12 -> WS2812-24`。

实际接线约定：

- `WS2812-8 DI` 接泰山派 19 号引脚。
- `WS2812-8 DO` 接 `WS2812-12 DI`。
- `WS2812-12 DO` 接 `WS2812-24 DI`。
- RGB 颜色保持旧 8 环颜色。
- 三段亮度独立控制。
- 新增 12 灯环与 24 灯环默认亮度均为 20%。
- 旧 8 灯环默认亮度保持 50%。

## 规划落盘文件

本轮实施计划已落盘到：

- `plans/20260512_voice_stream_ws2812_cascade.md`

## 修改文件

本轮涉及的代码与板端启动脚本改动文件：

- `board/ws2812/ws2812_spi.py`
- `tools/adb_ws2812_ring.py`
- `tools/adb_imx415_rknn_live_view.py`
- `tools/minimind_o_voice_runner.py`
- `tools/chip_capture_gui/settings.py`
- `tools/chip_capture_gui/ws2812.py`
- `tools/chip_capture_gui/voice_assistant.py`
- `tools/chip_capture_gui/opencv_app.py`
- `tools/chip_capture_gui/app.py`
- `board/desktop/chipcheck-hdmi-gui`

## WS2812 级联控制要点

底层 SPI 写灯逻辑已改为一次性写出 44 个像素，对应 `8 + 12 + 24` 三段级联。

新增参数：

- `--segment-counts`
- `--segment-brightness`

默认值：

- `--segment-counts 8,12,24`
- `--segment-brightness 0.50,0.20,0.20`

关键约束：

- 级联灯带必须一次性按物理顺序写出完整 44 灯数据。
- 不能对 8、12、24 三段分别调用三次写灯命令。
- 如果分三次写，后一次会从第一个灯重新移位写入，导致前段被覆盖，整体显示错位。

GUI 行为：

- 原 `Light` 仍控制旧 8 灯环亮度。
- 新增 `High Light` / `Low Light`，或键盘命令 `light_high` / `light_low`，用于控制新增 12 灯环与 24 灯环亮度。
- RGB 颜色仍沿用旧 8 环颜色设置，不为三段拆分颜色。
- PC live view 的默认 runtime setup 已同步为 44 灯三段配置。

## 语音流式 overlay 要点

`VoiceAssistantController` 增加：

- `stream_text` 占位符文件。
- reply 文本缓存。
- TTL 自动消失逻辑。

`tools/minimind_o_voice_runner.py` 增加：

- `--stream-text` 参数。
- 生成过程中持续写入当前模型回复文本，让 GUI 能边生成边读取。

OpenCV GUI 增加：

- 持续读取语音助手 stream 文本。
- 在画面左上角用绿色文字绘制当前 MiniMind-O 回复。
- 中文绘制使用 Pillow 与文泉驿字体 `wqy-zenhei.ttc`。
- 长文本支持在当前显示窗口内滚动。
- `[` 和 `]` 用于滚动文本。
- `\` 用于重置为跟随最新文本。

桌面启动脚本：

- `board/desktop/chipcheck-hdmi-gui` 已接入 `--stream-text`，启动 HDMI GUI 时会把模型流式文本路径传给 MiniMind-O runner。

## 验证结果

本地与板端验证结果：

- 本地 `py_compile` 通过。
- 板端 `py_compile` 通过。
- 板端已确认存在 PIL。
- 板端已确认存在字体：`/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`。
- overlay 绘制函数生成测试图：`/tmp/chipcheck_voice_overlay_test.jpg`。
- overlay 绘制测试结果：`bottom=59 nonzero=27204`。
- `tools/minimind_o_voice_runner.py --stream-text` 以 4 token 测试成功。
- `stream.txt` 写入内容：`你好！我很高兴`。
- 上述 MiniMind-O 4 token 流式测试耗时约 `55.7s`。
- WS2812 44 灯测试返回：`count=44 segments=8,12,24 brightness=0.500,0.200,0.200`。
- `LocalWs2812Controller apply/set_brightnesses` 验证成功。
- WS2812 默认亮度已恢复为 `0.50/0.20/0.20`。
- PC 短帧视觉 smoke 通过。
- PC smoke 输出包含：`Runtime setup: WS2812 rgb=190,255,100 brightness=0.50/0.20/0.20`。
- PC smoke 输出包含：`Processed frames: 5`。

## 风险与使用注意

- 流式文字仍要等 MiniMind-O 模型加载完成后才开始出现。
- MiniMind-O 当前仍走 CPU 推理，首次回复延迟仍约一分钟量级。
- 滚动只在当前 overlay 显示 TTL 内有效；TTL 结束后文字会自动消失。
- 灯光默认已经恢复到 `0.50/0.20/0.20`，即旧 8 环 50%，新增 12/24 环各 20%。
- 级联三环调光时，应优先使用本轮新增的一次性 44 灯写入接口和三段亮度参数。
- 桌面启动脚本已传入 `--stream-text`，正常从 HDMI GUI 启动时会启用左上角绿色流式回复 overlay。

## 后续检索关键词

MiniMind-O, stream-text, stream_text, voice overlay, 绿色文字, TTL, Pillow, wqy-zenhei, WS2812, 44 lights, segment-counts, segment-brightness, 8,12,24, High Light, Low Light, light_high, light_low, chipcheck-hdmi-gui

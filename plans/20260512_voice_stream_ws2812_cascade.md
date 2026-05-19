# 2026-05-12 Voice Stream Overlay and WS2812 Cascade Plan

## Goals

- Show MiniMind-O replies as green text over the camera image at the top-left.
- Update reply text while the model is generating, then keep it visible briefly and auto-hide.
- Allow scrolling through long replies on the board OpenCV GUI without blocking detection.
- Drive the cascaded WS2812 rings as one strip: 8 camera-close LEDs, 12 high-angle far-field LEDs, 24 low-angle near-field LEDs.
- Keep the existing RGB color for all three rings, while making brightness independent.

## Decisions

- The original 8-LED brightness remains the existing `Light` setting.
- New defaults:
  - 8 close ring: existing default `0.50`
  - 12 high-angle far ring: `0.20`
  - 24 low-angle near ring: `0.20`
- Because the LEDs are cascaded, the SPI script must write all 44 pixels in one transaction. Segment writes must not be implemented as separate calls.
- The MiniMind-O runner writes a plain text stream file during generation. GUI reads that file periodically and overlays the content.
- OpenCV board GUI gets the full overlay and keyboard scrolling first because it is the board HDMI entry.
- Qt GUI also receives the same voice stream path/settings so PC/local runs stay compatible.

## Implementation Steps

1. Extend `board/ws2812/ws2812_spi.py` with segment counts and per-segment brightness.
2. Extend `LightSettings` and WS2812 controllers to call the board script once with `--segment-counts` and `--segment-brightness`.
3. Add high/low ring brightness CLI arguments and GUI controls.
4. Extend `VoiceAssistantController` with `stream_text`, `reply_display_text`, and `reply_visible_until`.
5. Extend `tools/minimind_o_voice_runner.py` to accept `--stream-text` and write incremental reply text during generation.
6. Draw a green semi-transparent reply overlay in `opencv_app.py`, with scroll keys for long replies.
7. Deploy changed files to the board and run syntax, WS2812, voice-stream, and vision smoke checks.
8. Archive the completed change in `history/`.

## Risks

- Streaming still only starts after the model has loaded and begins generation; MiniMind-O CPU startup latency remains large.
- The board has no swap and only 4GB RAM, so long voice generations can still compete with GUI CPU/memory.
- The exact physical order is assumed to be `8 -> 12 -> 24` because wiring is DI into 8, then DO to 12, then DO to 24.

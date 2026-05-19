# WS2812-256 independent backlight GPIO channel

Updated: 2026-05-13

## Request

Add a non-cascaded WS2812-256 rectangular backlight array to the current
TaishanPi 3M RK3576 + IMX678 ChipCheck system. The existing WS2812-8/12/24
ring chain must remain on SPI1 MOSI pin 19 and keep one-shot 44-pixel writes.
The new backlight should be controlled from the GUI like the other lights,
default to 20% brightness, and reuse the existing RGB default.

## Hardware decision

- Existing 8/12/24 rings stay on 40-pin physical pin 19, `SPI1_MOSI(M1) /
  GPIO2_C2`, via `/dev/spidev1.0`.
- New WS2812-256 backlight DI default is 40-pin physical pin 38,
  `GPIO3_A2`, exposed as `gpiochip3 line 2`.
- The implementation keeps the GPIO configurable through CLI fields:
  `--backlight-gpio`, `--backlight-gpio-chip`, `--backlight-gpio-line`, and
  `--backlight-count`.
- The backlight should use external 5V power sized for the array current and
  share GND with TaishanPi. Keep the usual WS2812 data resistor and use a
  3.3V-to-5V logic buffer if the array is unreliable with 3.3V DI.

## Software changes

- Added board-side independent backlight wrapper:
  `board/ws2812/ws2812_gpio.py`.
- Added RK GPIO MMIO timing helper:
  `board/ws2812/ws2812_gpio_mmio.c`.
- Extended deployment/control tool:
  `tools/adb_ws2812_ring.py`.
  - `install-script` now pushes the backlight Python wrapper and C helper.
  - The board compiles `ws2812_gpio_mmio` when `cc` or `gcc` is available.
  - It attempts `chown root:root`, `chmod 4755`, and `setcap
    cap_sys_rawio,cap_sys_nice+ep`; failures are warnings.
  - `set` / `off` can drive both the 44-pixel ring chain and the independent
    256-pixel backlight, with `--no-backlight` to skip the new channel.
- Extended GUI light state:
  `tools/chip_capture_gui/settings.py`,
  `tools/chip_capture_gui/ws2812.py`,
  `tools/chip_capture_gui/app.py`.
  - Added `Back Light` slider.
  - Defaults are `Light 50%`, `High Light 20%`, `Low Light 20%`,
    `Back Light 20%`.
  - RGB stays `190,255,100`.
  - `off()` shuts down all four light channels.
- Extended realtime and capture setup:
  `tools/adb_imx415_rknn_live_view.py`,
  `tools/seg_cvat_pipeline.py`.
  - Runtime setup applies the independent backlight by default.
  - Backlight failure is reported as a warning and does not block the camera
    stream.
- Updated GUI README with the new default and pin recommendation.

## Verification

Local syntax checks passed:

```powershell
python -m py_compile .\board\ws2812\ws2812_gpio.py .\tools\adb_ws2812_ring.py .\tools\chip_capture_gui\settings.py .\tools\chip_capture_gui\ws2812.py .\tools\chip_capture_gui\app.py .\tools\adb_imx415_rknn_live_view.py .\tools\seg_cvat_pipeline.py
```

CLI help checks showed the new backlight options in:

```powershell
python .\tools\adb_ws2812_ring.py set --help
python .\tools\adb_imx415_rknn_live_view.py --help
python .\tools\seg_cvat_pipeline.py capture --help
python -m tools.chip_capture_gui --help
python .\board\ws2812\ws2812_gpio.py --help
```

C helper syntax check passed under WSL GCC:

```powershell
wsl.exe sh -lc "gcc -std=gnu11 -Wall -Wextra -fsyntax-only '/mnt/f/WORKSPACE/chipCheck/-IMX415_Vision/board/ws2812/ws2812_gpio_mmio.c'"
```

## Board validation

ADB serial `2e2609c37dc21c0a` was online on 2026-05-13.

Initial status confirmed:

- `/dev/spidev1.0` exists and is owned `root:plugdev`.
- `/boot/overlays/tspi-3m-spi1m1-spidev.dtbo` exists.
- `/boot/ubootEnv.txt` contains `overlays=tspi-3m-spi1m1-spidev.dtbo`.
- Existing `/userdata/rknn_yolo11_demo/ws2812_spi.py` exists.
- Backlight script/helper did not exist before install.

Deployment command:

```powershell
python .\tools\adb_ws2812_ring.py install-script
```

Result:

- Pushed `/userdata/rknn_yolo11_demo/ws2812_gpio.py`.
- Pushed `/userdata/rknn_yolo11_demo/ws2812_gpio_mmio.c`.
- Compiled `/userdata/rknn_yolo11_demo/ws2812_gpio_mmio`.
- Helper permission after install: `-rwsr-xr-x root root`.
- No compile, chmod, chown, or setcap warning was observed.

Smoke commands completed successfully:

```powershell
python .\tools\adb_ws2812_ring.py set --brightness 0.10 --segment-brightness 0.10,0.05,0.05 --no-backlight
python .\tools\adb_ws2812_ring.py set --brightness 0.10 --segment-brightness 0.10,0.05,0.05 --backlight-brightness 0.03
python .\tools\adb_ws2812_ring.py set --brightness 0.50 --segment-brightness 0.50,0.20,0.20 --backlight-brightness 0.20
```

Observed backlight output:

```text
ws2812-gpio-mmio count=256 line=2 brightness=0.030 ... base=0x2ae30000
ws2812-backlight count=256 gpio=GPIO3_A2 ... brightness=0.030 ...
ws2812-gpio-mmio count=256 line=2 brightness=0.200 ... base=0x2ae30000
ws2812-backlight count=256 gpio=GPIO3_A2 ... brightness=0.200 ...
```

The command path for both the 44-pixel ring chain and the independent 256-pixel
backlight is validated. This does not replace visual confirmation of actual LED
color/order on the physical array.

## Remaining risks

- WS2812 is timing-sensitive. The helper uses `/dev/mem` MMIO busy-wait timing
  with best-effort realtime scheduling, which is far stronger than sysfs or
  libgpiod bit toggling but still not as deterministic as hardware SPI, DMA,
  PWM, an LED controller, or a small MCU.
- If the 256 array flickers or shows wrong colors, first verify 5V power,
  common ground, and logic-level conversion; then consider moving the backlight
  to a hardware-timed output path.

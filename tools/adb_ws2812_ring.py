#!/usr/bin/env python3
"""Deploy and control ChipCheck WS2812 lighting on TaishanPi 3M."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADB = os.environ.get("ADB", r"C:\Users\Kaltsit\AppData\Local\Android\Sdk\platform-tools\adb.exe")
DEFAULT_SERIAL = "2e2609c37dc21c0a"
OVERLAY_NAME = "tspi-3m-spi1m1-spidev.dtbo"
LOCAL_OVERLAY_DTS = ROOT / "board" / "overlays" / "tspi-3m-spi1m1-spidev.dts"
LOCAL_BOARD_SCRIPT = ROOT / "board" / "ws2812" / "ws2812_spi.py"
LOCAL_BACKLIGHT_SCRIPT = ROOT / "board" / "ws2812" / "ws2812_gpio.py"
LOCAL_BACKLIGHT_HELPER_C = ROOT / "board" / "ws2812" / "ws2812_gpio_mmio.c"
REMOTE_SCRIPT = "/userdata/rknn_yolo11_demo/ws2812_spi.py"
REMOTE_BACKLIGHT_SCRIPT = "/userdata/rknn_yolo11_demo/ws2812_gpio.py"
REMOTE_BACKLIGHT_HELPER = "/userdata/rknn_yolo11_demo/ws2812_gpio_mmio"
REMOTE_BACKLIGHT_HELPER_C = "/userdata/rknn_yolo11_demo/ws2812_gpio_mmio.c"
DEFAULT_SEGMENT_COUNTS = "8,12,24"
DEFAULT_SEGMENT_BRIGHTNESS = "0.50,0.20,0.20"
DEFAULT_RGB = "190,255,100"


def adb_cmd(args: argparse.Namespace, *parts: str) -> list[str]:
    command = [args.adb]
    if args.serial:
        command.extend(["-s", args.serial])
    command.extend(parts)
    return command


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}:", file=sys.stderr)
        print(" ".join(shlex.quote(part) for part in command), file=sys.stderr)
        if exc.stdout and exc.stdout.strip():
            print("\n[stdout]", file=sys.stderr)
            print(exc.stdout.strip(), file=sys.stderr)
        if exc.stderr and exc.stderr.strip():
            print("\n[stderr]", file=sys.stderr)
            print(exc.stderr.strip(), file=sys.stderr)
        raise SystemExit(exc.returncode) from exc


def shell(args: argparse.Namespace, script: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(adb_cmd(args, "shell", script), check=check)


def push(args: argparse.Namespace, local: Path, remote: str) -> None:
    result = run(adb_cmd(args, "push", str(local), remote))
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


def install_overlay(args: argparse.Namespace) -> None:
    if not LOCAL_OVERLAY_DTS.exists():
        raise SystemExit(f"missing overlay source: {LOCAL_OVERLAY_DTS}")

    remote_dts = "/tmp/tspi-3m-spi1m1-spidev.dts"
    remote_dtbo = f"/boot/overlays/{OVERLAY_NAME}"
    push(args, LOCAL_OVERLAY_DTS, remote_dts)

    install = f"""
set -e
dtc -@ -I dts -O dtb -o {shlex.quote(remote_dtbo)} {shlex.quote(remote_dts)}
if ! grep -q '{OVERLAY_NAME}' /boot/ubootEnv.txt; then
  cp /boot/ubootEnv.txt /boot/ubootEnv.txt.bak.before-ws2812-spi1-$(date +%Y%m%d-%H%M%S)
  if grep -q '^overlays=' /boot/ubootEnv.txt; then
    sed -i '0,/^overlays=/s/^overlays=.*/& {OVERLAY_NAME}/' /boot/ubootEnv.txt
  else
    printf '\\n# Enable SPI1 M1 spidev for WS2812 on 40Pin pin 19\\noverlays={OVERLAY_NAME}\\n' >> /boot/ubootEnv.txt
  fi
fi
ls -l {shlex.quote(remote_dtbo)}
grep '^overlays=' /boot/ubootEnv.txt || true
"""
    result = shell(args, install)
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


def install_script(args: argparse.Namespace) -> None:
    if not LOCAL_BOARD_SCRIPT.exists():
        raise SystemExit(f"missing board script: {LOCAL_BOARD_SCRIPT}")
    if not LOCAL_BACKLIGHT_SCRIPT.exists():
        raise SystemExit(f"missing backlight script: {LOCAL_BACKLIGHT_SCRIPT}")
    if not LOCAL_BACKLIGHT_HELPER_C.exists():
        raise SystemExit(f"missing backlight helper source: {LOCAL_BACKLIGHT_HELPER_C}")
    shell(args, "mkdir -p /userdata/rknn_yolo11_demo")
    push(args, LOCAL_BOARD_SCRIPT, REMOTE_SCRIPT)
    push(args, LOCAL_BACKLIGHT_SCRIPT, REMOTE_BACKLIGHT_SCRIPT)
    push(args, LOCAL_BACKLIGHT_HELPER_C, REMOTE_BACKLIGHT_HELPER_C)
    install = f"""
set -u
chmod +x {shlex.quote(REMOTE_SCRIPT)} {shlex.quote(REMOTE_BACKLIGHT_SCRIPT)}
compiler="$(command -v cc || command -v gcc || true)"
if [ -n "$compiler" ]; then
  if "$compiler" -O2 -Wall -Wextra -o {shlex.quote(REMOTE_BACKLIGHT_HELPER)} {shlex.quote(REMOTE_BACKLIGHT_HELPER_C)}; then
    chmod +x {shlex.quote(REMOTE_BACKLIGHT_HELPER)}
    chown root:root {shlex.quote(REMOTE_BACKLIGHT_HELPER)} 2>/dev/null || echo 'warning: chown root:root ws2812_gpio_mmio failed' >&2
    chmod 4755 {shlex.quote(REMOTE_BACKLIGHT_HELPER)} 2>/dev/null || echo 'warning: chmod 4755 ws2812_gpio_mmio failed' >&2
    setcap cap_sys_rawio,cap_sys_nice+ep {shlex.quote(REMOTE_BACKLIGHT_HELPER)} 2>/dev/null || echo 'warning: setcap ws2812_gpio_mmio failed' >&2
  else
    echo 'warning: failed to compile ws2812_gpio_mmio on board' >&2
  fi
else
  echo 'warning: no cc/gcc found on board; ws2812_gpio_mmio was not compiled' >&2
fi
ls -l {shlex.quote(REMOTE_SCRIPT)} {shlex.quote(REMOTE_BACKLIGHT_SCRIPT)} {shlex.quote(REMOTE_BACKLIGHT_HELPER_C)} 2>/dev/null || true
ls -l {shlex.quote(REMOTE_BACKLIGHT_HELPER)} 2>/dev/null || true
"""
    result = shell(args, install, check=False)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    print(f"Installed board script: {REMOTE_SCRIPT}")
    print(f"Installed backlight script: {REMOTE_BACKLIGHT_SCRIPT}")
    print(f"Installed backlight helper source: {REMOTE_BACKLIGHT_HELPER_C}")


def status(args: argparse.Namespace) -> None:
    result = shell(
        args,
        f"""
echo 'serial:'
cat /proc/device-tree/serial-number 2>/dev/null || true; echo
echo 'spidev:'
ls -l /dev/spidev* 2>/dev/null || true
echo 'overlay:'
ls -l /boot/overlays/{OVERLAY_NAME} 2>/dev/null || true
grep '^overlays=' /boot/ubootEnv.txt || true
echo 'script:'
ls -l {shlex.quote(REMOTE_SCRIPT)} 2>/dev/null || true
echo 'backlight script/helper:'
ls -l {shlex.quote(REMOTE_BACKLIGHT_SCRIPT)} {shlex.quote(REMOTE_BACKLIGHT_HELPER)} {shlex.quote(REMOTE_BACKLIGHT_HELPER_C)} 2>/dev/null || true
""",
        check=False,
    )
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


def set_color(args: argparse.Namespace, off: bool = False) -> None:
    remote_args = [
        "python3",
        REMOTE_SCRIPT,
        "--device",
        args.device,
        "--count",
        str(args.count),
        "--brightness",
        str(args.brightness),
    ]
    if getattr(args, "segment_counts", ""):
        remote_args.extend(["--segment-counts", args.segment_counts])
    if getattr(args, "segment_brightness", ""):
        remote_args.extend(["--segment-brightness", args.segment_brightness])
    if getattr(args, "segment_rgb", ""):
        remote_args.extend(["--segment-rgb", args.segment_rgb])
    if off:
        remote_args.append("--off")
    else:
        remote_args.extend(["--rgb", args.rgb])
    result = shell(args, " ".join(shlex.quote(part) for part in remote_args))
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if getattr(args, "no_backlight", False):
        return

    backlight_args = [
        "python3",
        REMOTE_BACKLIGHT_SCRIPT,
        "--gpio",
        args.backlight_gpio,
        "--chip",
        args.backlight_chip,
        "--line",
        str(args.backlight_line),
        "--count",
        str(args.backlight_count),
        "--brightness",
        str(args.backlight_brightness),
        "--helper",
        REMOTE_BACKLIGHT_HELPER,
    ]
    if off:
        backlight_args.append("--off")
    else:
        backlight_args.extend(["--rgb", args.backlight_rgb or args.rgb])
    result = shell(args, " ".join(shlex.quote(part) for part in backlight_args))
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


def add_backlight_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backlight-brightness", type=float, default=0.20, help="Backlight WS2812 brightness, 0.0..1.0")
    parser.add_argument("--backlight-rgb", default="", help="Backlight RGB color; defaults to --rgb")
    parser.add_argument("--backlight-count", type=int, default=256, help="Backlight WS2812 LED count")
    parser.add_argument("--backlight-gpio", default="GPIO3_A2", help="Backlight GPIO name")
    parser.add_argument("--backlight-chip", default="gpiochip3", help="Backlight GPIO chip label")
    parser.add_argument("--backlight-line", type=int, default=2, help="Backlight GPIO line inside the bank")
    parser.add_argument("--no-backlight", action="store_true", help="Do not set the independent backlight channel")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=DEFAULT_ADB, help="Path to adb.exe")
    parser.add_argument("--serial", default=DEFAULT_SERIAL, help="ADB serial")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("install-overlay", help="Install SPI1 M1 spidev overlay; reboot required")
    subparsers.add_parser("install-script", help="Push the board-side WS2812 SPI script")
    deploy = subparsers.add_parser("deploy", help="Install overlay and board script")
    deploy.add_argument("--reboot", action="store_true", help="Reboot after installing the overlay")
    subparsers.add_parser("status", help="Show overlay, spidev and script status")

    set_parser = subparsers.add_parser("set", help="Set all LEDs to one RGB color")
    set_parser.add_argument("--rgb", default=DEFAULT_RGB, help="RGB color, for example 80,80,80")
    set_parser.add_argument("--brightness", type=float, default=0.50, help="Brightness multiplier, 0.0..1.0")
    set_parser.add_argument("--count", type=int, default=44, help="LED count")
    set_parser.add_argument("--segment-counts", default=DEFAULT_SEGMENT_COUNTS, help="Cascaded segment counts")
    set_parser.add_argument("--segment-brightness", default=DEFAULT_SEGMENT_BRIGHTNESS, help="Cascaded segment brightness values")
    set_parser.add_argument("--segment-rgb", default="", help="Semicolon-separated RGB values for cascaded segments")
    set_parser.add_argument("--device", default="/dev/spidev1.0", help="Linux spidev node")
    add_backlight_args(set_parser)

    off_parser = subparsers.add_parser("off", help="Turn LEDs off")
    off_parser.add_argument("--brightness", type=float, default=0.0, help=argparse.SUPPRESS)
    off_parser.add_argument("--count", type=int, default=44, help="LED count")
    off_parser.add_argument("--segment-counts", default=DEFAULT_SEGMENT_COUNTS, help="Cascaded segment counts")
    off_parser.add_argument("--segment-brightness", default=DEFAULT_SEGMENT_BRIGHTNESS, help="Cascaded segment brightness values")
    off_parser.add_argument("--segment-rgb", default="", help=argparse.SUPPRESS)
    off_parser.add_argument("--device", default="/dev/spidev1.0", help="Linux spidev node")
    add_backlight_args(off_parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "install-overlay":
        install_overlay(args)
        print("Overlay installed. Reboot the board before using /dev/spidev1.0.")
    elif args.command == "install-script":
        install_script(args)
    elif args.command == "deploy":
        install_overlay(args)
        install_script(args)
        if args.reboot:
            shell(args, "sync; reboot", check=False)
            print("Board reboot requested.")
        else:
            print("Deploy complete. Reboot the board before using /dev/spidev1.0.")
    elif args.command == "status":
        status(args)
    elif args.command == "set":
        set_color(args)
    elif args.command == "off":
        set_color(args, off=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

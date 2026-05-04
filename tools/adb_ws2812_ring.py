#!/usr/bin/env python3
"""Deploy and control a WS2812-8 ring on TaishanPi 3M through SPI1 MOSI."""

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
REMOTE_SCRIPT = "/userdata/rknn_yolo11_demo/ws2812_spi.py"


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
    shell(args, "mkdir -p /userdata/rknn_yolo11_demo")
    push(args, LOCAL_BOARD_SCRIPT, REMOTE_SCRIPT)
    shell(args, f"chmod +x {shlex.quote(REMOTE_SCRIPT)}")
    print(f"Installed board script: {REMOTE_SCRIPT}")


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
    if off:
        remote_args.append("--off")
    else:
        remote_args.extend(["--rgb", args.rgb])
    result = shell(args, " ".join(shlex.quote(part) for part in remote_args))
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


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
    set_parser.add_argument("--rgb", default="255,255,255", help="RGB color, for example 80,80,80")
    set_parser.add_argument("--brightness", type=float, default=0.25, help="Brightness multiplier, 0.0..1.0")
    set_parser.add_argument("--count", type=int, default=8, help="LED count")
    set_parser.add_argument("--device", default="/dev/spidev1.0", help="Linux spidev node")

    off_parser = subparsers.add_parser("off", help="Turn LEDs off")
    off_parser.add_argument("--brightness", type=float, default=0.0, help=argparse.SUPPRESS)
    off_parser.add_argument("--count", type=int, default=8, help="LED count")
    off_parser.add_argument("--device", default="/dev/spidev1.0", help="Linux spidev node")
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

#!/usr/bin/env python3
"""Drive an independent WS2812 backlight strip through RK GPIO MMIO."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_GPIO = "GPIO3_A2"
DEFAULT_COUNT = 256
DEFAULT_BRIGHTNESS = 0.20
DEFAULT_RGB = (190, 255, 100)
DEFAULT_HELPER = "/userdata/rknn_yolo11_demo/ws2812_gpio_mmio"
DEVICE_TREE_ROOT = Path("/proc/device-tree")


GPIO_NAME_RE = re.compile(r"^GPIO(?P<bank>\d+)_(?P<port>[A-Da-d])(?P<pin>[0-7])$")
GPIO_NODE_RE = re.compile(r"gpio@(?P<base>[0-9a-fA-F]+)")


def parse_rgb(text: str) -> tuple[int, int, int]:
    parts = text.replace(";", ",").split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected R,G,B")
    try:
        values = tuple(int(part.strip()) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("RGB values must be integers") from exc
    if any(value < 0 or value > 255 for value in values):
        raise argparse.ArgumentTypeError("RGB values must be in 0..255")
    return values  # type: ignore[return-value]


def parse_gpio_name(text: str) -> tuple[int, int]:
    match = GPIO_NAME_RE.match(text)
    if match is None:
        raise argparse.ArgumentTypeError("expected GPIO bank/port/pin name such as GPIO3_A2")
    bank = int(match.group("bank"))
    port = ord(match.group("port").upper()) - ord("A")
    pin = int(match.group("pin"))
    return bank, port * 8 + pin


def read_dt_string(path: Path) -> str:
    data = path.read_bytes().split(b"\0", 1)[0]
    return data.decode("ascii", errors="replace")


def read_dt_u32_cells(path: Path) -> list[int]:
    data = path.read_bytes()
    usable = len(data) - (len(data) % 4)
    return [int.from_bytes(data[offset : offset + 4], "big") for offset in range(0, usable, 4)]


def find_dt_int_property(node: Path, name: str, default: int) -> int:
    current = node
    while current != current.parent:
        prop = current / name
        if prop.exists():
            cells = read_dt_u32_cells(prop)
            if cells:
                return int(cells[0])
        if current == DEVICE_TREE_ROOT:
            break
        current = current.parent
    return default


def gpio_alias_node(bank: int) -> Path:
    alias_path = DEVICE_TREE_ROOT / "aliases" / f"gpio{bank}"
    if not alias_path.exists():
        raise FileNotFoundError(f"missing device-tree alias: {alias_path}")
    node_text = read_dt_string(alias_path)
    if not node_text:
        raise RuntimeError(f"empty device-tree alias: {alias_path}")
    if node_text.startswith("/"):
        return DEVICE_TREE_ROOT / node_text.lstrip("/")
    return DEVICE_TREE_ROOT / node_text


def infer_base_from_reg(node: Path) -> int | None:
    reg_path = node / "reg"
    if not reg_path.exists():
        return None
    cells = read_dt_u32_cells(reg_path)
    address_cells = find_dt_int_property(node.parent, "#address-cells", 2)
    if address_cells <= 0 or len(cells) < address_cells:
        return None
    base = 0
    for cell in cells[:address_cells]:
        base = (base << 32) | int(cell)
    return base


def infer_base_from_node_name(node: Path) -> int | None:
    for part in reversed(node.parts):
        match = GPIO_NODE_RE.search(part)
        if match is not None:
            return int(match.group("base"), 16)
    return None


def infer_gpio_base(bank: int) -> int:
    if not DEVICE_TREE_ROOT.exists():
        raise RuntimeError(f"{DEVICE_TREE_ROOT} is not available; pass --base explicitly")
    node = gpio_alias_node(bank)
    if not node.exists():
        raise FileNotFoundError(f"device-tree GPIO node does not exist: {node}")
    base = infer_base_from_reg(node)
    if base is not None:
        return base
    base = infer_base_from_node_name(node)
    if base is not None:
        return base
    raise RuntimeError(f"cannot infer GPIO bank base from {node}; pass --base explicitly")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpio", default=DEFAULT_GPIO, help="GPIO name, for example GPIO3_A2")
    parser.add_argument("--chip", help="GPIO chip label for diagnostics; default derives from --gpio")
    parser.add_argument("--line", type=int, help="GPIO line inside the bank; default derives from --gpio")
    parser.add_argument("--base", type=lambda value: int(value, 0), help="GPIO bank physical base address override")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="WS2812 LED count")
    parser.add_argument("--rgb", type=parse_rgb, default=DEFAULT_RGB, help="RGB color, for example 190,255,100")
    parser.add_argument("--brightness", type=float, default=DEFAULT_BRIGHTNESS, help="Brightness multiplier, 0.0..1.0")
    parser.add_argument("--helper", default=DEFAULT_HELPER, help="Path to ws2812_gpio_mmio helper")
    parser.add_argument("--off", action="store_true", help="Turn all LEDs off")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        bank, derived_line = parse_gpio_name(args.gpio)
    except argparse.ArgumentTypeError as exc:
        raise SystemExit(str(exc)) from exc

    line = derived_line if args.line is None else args.line
    chip = args.chip or f"gpiochip{bank}"
    if args.count <= 0:
        raise SystemExit("--count must be > 0")
    if not 0 <= line <= 31:
        raise SystemExit("--line must be in 0..31")
    if not 0.0 <= args.brightness <= 1.0:
        raise SystemExit("--brightness must be in 0.0..1.0")

    try:
        base = int(args.base) if args.base is not None else infer_gpio_base(bank)
    except Exception as exc:  # noqa: BLE001 - concise board-side diagnostic
        raise SystemExit(f"failed to infer GPIO base for {args.gpio}: {exc}") from exc

    helper = Path(args.helper)
    if not helper.exists():
        raise SystemExit(f"helper not found: {helper}")
    if not os.access(helper, os.X_OK):
        raise SystemExit(f"helper is not executable: {helper}")

    rgb = (0, 0, 0) if args.off else args.rgb
    remote_args = [
        str(helper),
        "--base",
        f"0x{base:x}",
        "--line",
        str(line),
        "--count",
        str(args.count),
        "--brightness",
        f"{args.brightness:.6f}",
        "--rgb",
        ",".join(str(channel) for channel in args.rgb),
    ]
    if args.off:
        remote_args.append("--off")

    result = subprocess.run(remote_args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        return result.returncode

    print(
        "ws2812-backlight "
        f"count={args.count} gpio={args.gpio} chip={chip} line={line} "
        f"brightness={args.brightness:.3f} rgb={rgb} base=0x{base:x}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

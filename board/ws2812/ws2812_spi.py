#!/usr/bin/env python3
"""Drive a small WS2812 ring through Linux spidev.

The encoder uses 3 SPI bits per WS2812 bit at 2.4 MHz:
  0 -> 100
  1 -> 110

Pixels are sent in GRB order, which is the usual WS2812 order.
"""

from __future__ import annotations

import argparse
import array
import fcntl
import os
import time
from pathlib import Path


SPI_IOC_WR_MODE = 0x40016B01
SPI_IOC_WR_BITS_PER_WORD = 0x40016B03
SPI_IOC_WR_MAX_SPEED_HZ = 0x40046B04

DEFAULT_DEVICE = "/dev/spidev1.0"
DEFAULT_SPEED_HZ = 2_400_000
DEFAULT_COUNT = 8


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


def clamp_u8(value: float) -> int:
    return max(0, min(255, int(round(value))))


def scale_rgb(rgb: tuple[int, int, int], brightness: float) -> tuple[int, int, int]:
    return tuple(clamp_u8(channel * brightness) for channel in rgb)  # type: ignore[return-value]


def encode_byte(value: int, out_bits: list[int]) -> None:
    for bit_index in range(7, -1, -1):
        out_bits.extend((1, 1, 0) if (value & (1 << bit_index)) else (1, 0, 0))


def pack_bits(bits: list[int]) -> bytes:
    padding = (-len(bits)) % 8
    if padding:
        bits.extend([0] * padding)
    output = bytearray()
    for offset in range(0, len(bits), 8):
        value = 0
        for bit in bits[offset : offset + 8]:
            value = (value << 1) | bit
        output.append(value)
    return bytes(output)


def encode_pixels(pixels: list[tuple[int, int, int]]) -> bytes:
    bits: list[int] = []
    for red, green, blue in pixels:
        encode_byte(green, bits)
        encode_byte(red, bits)
        encode_byte(blue, bits)
    reset = bytes(32)
    return reset + pack_bits(bits) + reset


def open_spi(device: str, speed_hz: int) -> int:
    fd = os.open(device, os.O_WRONLY)
    try:
        fcntl.ioctl(fd, SPI_IOC_WR_MODE, array.array("B", [0]), True)
        fcntl.ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, array.array("B", [8]), True)
        fcntl.ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, array.array("I", [speed_hz]), True)
    except Exception:
        os.close(fd)
        raise
    return fd


def show(device: str, speed_hz: int, pixels: list[tuple[int, int, int]]) -> None:
    payload = encode_pixels(pixels)
    fd = open_spi(device, speed_hz)
    try:
        os.write(fd, payload)
        time.sleep(0.001)
    finally:
        os.close(fd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="Linux spidev node")
    parser.add_argument("--speed", type=int, default=DEFAULT_SPEED_HZ, help="SPI speed in Hz")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="WS2812 LED count")
    parser.add_argument("--rgb", type=parse_rgb, default=(255, 255, 255), help="RGB color, for example 80,80,80")
    parser.add_argument("--brightness", type=float, default=0.25, help="Brightness multiplier, 0.0..1.0")
    parser.add_argument("--off", action="store_true", help="Turn all LEDs off")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.count <= 0:
        raise SystemExit("--count must be > 0")
    if args.speed <= 0:
        raise SystemExit("--speed must be > 0")
    if not 0.0 <= args.brightness <= 1.0:
        raise SystemExit("--brightness must be in 0.0..1.0")
    if not Path(args.device).exists():
        raise SystemExit(f"{args.device} does not exist; install the SPI overlay and reboot first")

    rgb = (0, 0, 0) if args.off else scale_rgb(args.rgb, args.brightness)
    show(args.device, args.speed, [rgb] * args.count)
    print(f"ws2812 count={args.count} rgb={rgb} device={args.device} speed={args.speed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

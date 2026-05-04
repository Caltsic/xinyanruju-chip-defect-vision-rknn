#!/usr/bin/env python3
"""Lightweight OpenCV GUI for reviewing one-class chip ROI labels."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import cv2

try:
    from tools.chip_roi_utils import (
        clamp_box,
        draw_chip_box,
        expand_box,
        load_yolo_box,
        read_image,
        save_yolo_label,
    )
except ModuleNotFoundError:  # allow running as .\tools\review_chip_roi_labels.py
    from chip_roi_utils import (
        clamp_box,
        draw_chip_box,
        expand_box,
        load_yolo_box,
        read_image,
        save_yolo_label,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "chip_roi" / "generated" / "existing_pseudo" / "manifest.csv"
WINDOW = "chip ROI review"


def read_manifest(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    for name in ("status", "reviewed_at", "x1", "y1", "x2", "y2"):
        if name not in fieldnames:
            fieldnames.append(name)
    return rows, fieldnames


def write_manifest(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def resolve_manifest_path(value: str, manifest_path: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [
        Path.cwd() / path,
        ROOT / path,
        manifest_path.parent / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return ROOT / path


def scale_for_display(width: int, height: int, max_width: int, max_height: int) -> float:
    return min(1.0, max_width / max(width, 1), max_height / max(height, 1))


def render(
    image,
    box: tuple[int, int, int, int] | None,
    row: dict[str, str],
    index: int,
    total: int,
    max_width: int,
    max_height: int,
):
    status = row.get("status", "")
    name = Path(row.get("image", "")).name
    text = f"{index + 1}/{total} {status} {name}"
    preview = draw_chip_box(image, box, text)
    scale = scale_for_display(preview.shape[1], preview.shape[0], max_width, max_height)
    if scale < 1.0:
        preview = cv2.resize(preview, (int(preview.shape[1] * scale), int(preview.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    return preview


def set_row_box(row: dict[str, str], box: tuple[int, int, int, int] | None) -> None:
    if box is None:
        row["x1"] = row["y1"] = row["x2"] = row["y2"] = ""
    else:
        row["x1"], row["y1"], row["x2"], row["y2"] = [str(value) for value in box]


def box_from_row(row: dict[str, str], width: int, height: int) -> tuple[int, int, int, int] | None:
    try:
        values = [row.get(name, "") for name in ("x1", "y1", "x2", "y2")]
        if all(value != "" for value in values):
            return clamp_box(tuple(int(float(value)) for value in values), width, height)
    except ValueError:
        return None
    return None


def update_review(
    row: dict[str, str],
    box: tuple[int, int, int, int] | None,
    status: str,
    width: int,
    height: int,
    manifest_path: Path,
) -> None:
    label_path = resolve_manifest_path(row["label"], manifest_path)
    save_yolo_label(label_path, box, width, height)
    row["status"] = status
    row["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
    set_row_box(row, box)


def next_review_index(rows: list[dict[str, str]], start: int, statuses: set[str]) -> int:
    if not statuses:
        return start
    for index in range(start, len(rows)):
        if rows[index].get("status", "") in statuses:
            return index
    return len(rows)


def parse_statuses(text: str) -> set[str]:
    return {part.strip() for part in text.split(",") if part.strip()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--only", default="candidate,needs_review", help="Comma-separated statuses to show; empty means all")
    parser.add_argument("--step", type=int, default=4, help="Move step for A/D/W/S")
    parser.add_argument(
        "--scale-step",
        type=float,
        default=0.01,
        help="Per-side expansion step for +/-; 0.01 changes width/height by about 2%%",
    )
    parser.add_argument("--max-width", type=int, default=1400)
    parser.add_argument("--max-height", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    rows, fieldnames = read_manifest(manifest_path)
    statuses = parse_statuses(args.only)
    index = next_review_index(rows, 0, statuses)
    if index >= len(rows):
        print("no rows to review")
        return 0

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    try:
        while index < len(rows):
            row = rows[index]
            image_path = resolve_manifest_path(row["image"], manifest_path)
            label_path = resolve_manifest_path(row["label"], manifest_path)
            image = read_image(image_path)
            height, width = image.shape[:2]
            box = load_yolo_box(label_path, width, height) or box_from_row(row, width, height)

            while True:
                cv2.imshow(WINDOW, render(image, box, row, index, len(rows), args.max_width, args.max_height))
                key = cv2.waitKeyEx(0)
                low = key & 0xFF
                if low in (27, ord("q")):
                    write_manifest(manifest_path, rows, fieldnames)
                    return 0
                if low in (13, 10):
                    update_review(row, box, "accepted" if box is not None else "negative", width, height, manifest_path)
                    write_manifest(manifest_path, rows, fieldnames)
                    index = next_review_index(rows, index + 1, statuses)
                    break
                if key in (3014656, 65535) or low in (127,):
                    box = None
                    update_review(row, box, "negative", width, height, manifest_path)
                    write_manifest(manifest_path, rows, fieldnames)
                    index = next_review_index(rows, index + 1, statuses)
                    break
                if box is None:
                    continue
                x1, y1, x2, y2 = box
                if low in (ord("a"), ord("A")):
                    box = clamp_box((x1 - args.step, y1, x2 - args.step, y2), width, height)
                elif low in (ord("d"), ord("D")):
                    box = clamp_box((x1 + args.step, y1, x2 + args.step, y2), width, height)
                elif low in (ord("w"), ord("W")):
                    box = clamp_box((x1, y1 - args.step, x2, y2 - args.step), width, height)
                elif low in (ord("s"), ord("S")):
                    box = clamp_box((x1, y1 + args.step, x2, y2 + args.step), width, height)
                elif low in (ord("+"), ord("=")):
                    box = expand_box(box, width, height, args.scale_step)
                elif low in (ord("-"), ord("_")):
                    box = expand_box(box, width, height, -args.scale_step)
    finally:
        cv2.destroyAllWindows()

    write_manifest(manifest_path, rows, fieldnames)
    print("review complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

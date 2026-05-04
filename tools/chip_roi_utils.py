#!/usr/bin/env python3
"""Shared helpers for chip ROI pseudo-label generation and review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(slots=True)
class ChipCandidate:
    box: tuple[int, int, int, int]
    score: float
    method: str


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"failed to read image: {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix or ".jpg", image)
    if not ok:
        raise RuntimeError(f"failed to encode image: {path}")
    encoded.tofile(str(path))


def clamp_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    x1 = max(0, min(width - 1, int(round(x1))))
    y1 = max(0, min(height - 1, int(round(y1))))
    x2 = max(0, min(width, int(round(x2))))
    y2 = max(0, min(height, int(round(y2))))
    if x2 <= x1:
        x2 = min(width, x1 + 1)
    if y2 <= y1:
        y2 = min(height, y1 + 1)
    return x1, y1, x2, y2


def expand_box(
    box: tuple[int, int, int, int],
    width: int,
    height: int,
    margin: float,
    min_side: int = 0,
    square: bool = False,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5
    bw = max(1.0, float(x2 - x1))
    bh = max(1.0, float(y2 - y1))
    if square:
        side = max(float(min_side), max(bw, bh) * (1.0 + 2.0 * margin))
        new_w = side
        new_h = side
    else:
        new_w = max(float(min_side), bw * (1.0 + 2.0 * margin))
        new_h = max(float(min_side), bh * (1.0 + 2.0 * margin))
    return clamp_box(
        (
            int(round(cx - new_w * 0.5)),
            int(round(cy - new_h * 0.5)),
            int(round(cx + new_w * 0.5)),
            int(round(cy + new_h * 0.5)),
        ),
        width,
        height,
    )


def box_to_yolo(box: tuple[int, int, int, int], width: int, height: int, class_id: int = 0) -> str:
    x1, y1, x2, y2 = box
    cx = ((x1 + x2) * 0.5) / width
    cy = ((y1 + y2) * 0.5) / height
    bw = (x2 - x1) / width
    bh = (y2 - y1) / height
    return f"{class_id} {cx:.8f} {cy:.8f} {bw:.8f} {bh:.8f}"


def yolo_to_box(line: str, width: int, height: int) -> tuple[int, int, int, int] | None:
    parts = line.strip().split()
    if len(parts) != 5:
        return None
    _, cx, cy, bw, bh = [float(part) for part in parts]
    x1 = int(round((cx - bw * 0.5) * width))
    y1 = int(round((cy - bh * 0.5) * height))
    x2 = int(round((cx + bw * 0.5) * width))
    y2 = int(round((cy + bh * 0.5) * height))
    return clamp_box((x1, y1, x2, y2), width, height)


def save_yolo_label(path: Path, box: tuple[int, int, int, int] | None, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if box is None:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(box_to_yolo(box, width, height) + "\n", encoding="utf-8")


def load_yolo_box(path: Path, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return yolo_to_box(line, width, height)
    return None


def locate_chip_dark_edge(
    image: np.ndarray,
    margin: float = 0.10,
    min_side: int = 0,
    square: bool = False,
    allow_fallback: bool = True,
    min_area_ratio: float = 0.0015,
    max_area_ratio: float = 0.92,
    center_bias: float = 8.0,
) -> ChipCandidate | None:
    """Find a likely chip region using dark-area and edge components.

    The heuristic is intentionally conservative: it finds a large dark/edge
    component, expands it with a small margin, and leaves final responsibility
    to the review GUI.
    """

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    border_y = max(4, height // 24)
    border_x = max(4, width // 24)
    border = np.concatenate(
        [
            blur[:border_y, :].ravel(),
            blur[-border_y:, :].ravel(),
            blur[:, :border_x].ravel(),
            blur[:, -border_x:].ravel(),
        ]
    )
    border_med = float(np.median(border))
    p42 = float(np.percentile(blur, 42))
    threshold = max(18.0, min(border_med - 18.0, p42))
    dark_mask = (blur < threshold).astype(np.uint8) * 255

    edges = cv2.Canny(blur, 45, 135)
    edge_mask = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    mask = cv2.bitwise_or(dark_mask, edge_mask)
    close_kernel = max(5, (min(width, height) // 70) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((close_kernel, close_kernel), np.uint8), iterations=2)
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(width * height)
    center_x = width * 0.5
    center_y = height * 0.5
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area_ratio = (w * h) / image_area
        if area_ratio < min_area_ratio or area_ratio > max_area_ratio:
            continue
        if w < 12 or h < 12:
            continue
        aspect = max(w / max(h, 1), h / max(w, 1))
        if aspect > 5.5:
            continue

        cx = x + w * 0.5
        cy = y + h * 0.5
        center_distance = ((cx - center_x) / width) ** 2 + ((cy - center_y) / height) ** 2
        roi_gray = gray[y : y + h, x : x + w]
        darkness = max(1.0, 255.0 - float(np.mean(roi_gray)))
        contour_area = max(1.0, float(cv2.contourArea(contour)))
        fill = min(1.0, contour_area / max(1.0, float(w * h)))
        touches_border = x <= 2 or y <= 2 or x + w >= width - 2 or y + h >= height - 2
        border_penalty = 0.65 if touches_border else 1.0
        centrality = 1.0 / (1.0 + center_bias * center_distance)
        score = area_ratio * darkness * (0.45 + 0.55 * fill) * centrality * border_penalty
        candidates.append((score, (x, y, x + w, y + h)))

    if candidates:
        score, raw_box = max(candidates, key=lambda item: item[0])
        return ChipCandidate(expand_box(raw_box, width, height, margin, min_side, square), score, "dark-edge")

    if not allow_fallback:
        return None

    side = max(int(round(min(width, height) * 0.42)), min_side)
    fallback = (
        int(round(center_x - side * 0.5)),
        int(round(center_y - side * 0.5)),
        int(round(center_x + side * 0.5)),
        int(round(center_y + side * 0.5)),
    )
    return ChipCandidate(expand_box(fallback, width, height, 0.0, min_side, square), 0.0, "fallback-center")


def draw_chip_box(
    image: np.ndarray,
    box: tuple[int, int, int, int] | None,
    text: str = "",
    color: tuple[int, int, int] = (255, 0, 255),
) -> np.ndarray:
    out = image.copy()
    if box is not None:
        x1, y1, x2, y2 = box
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 0), 5)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
    if text:
        cv2.rectangle(out, (0, 0), (out.shape[1], 28), (0, 0, 0), -1)
        cv2.putText(out, text[:140], (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(out, text[:140], (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)
    return out


def make_contact_sheet(items: list[tuple[str, np.ndarray]], path: Path, tile_w: int = 260, tile_h: int = 210) -> None:
    if not items:
        return
    cols = min(4, len(items))
    rows = (len(items) + cols - 1) // cols
    sheet = np.full((rows * tile_h, cols * tile_w, 3), 235, dtype=np.uint8)
    for index, (name, image) in enumerate(items):
        thumb = cv2.resize(image, (tile_w, tile_h), interpolation=cv2.INTER_AREA)
        cv2.rectangle(thumb, (0, 0), (tile_w - 1, 24), (255, 255, 255), -1)
        cv2.putText(thumb, name[:34], (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 1, cv2.LINE_AA)
        row = index // cols
        col = index % cols
        sheet[row * tile_h : (row + 1) * tile_h, col * tile_w : (col + 1) * tile_w] = thumb
    write_image(path, sheet)

from __future__ import annotations

import math

import cv2
import numpy as np

from tools.adb_imx415_rknn_live_view import Detection, polygon_area


def _box_to_pixels(detection: Detection, width: int, height: int) -> tuple[int, int, int, int] | None:
    values = [float(detection.x1), float(detection.y1), float(detection.x2), float(detection.y2)]
    if any(not math.isfinite(value) for value in values):
        return None
    x1, y1, x2, y2 = values
    if max(abs(value) for value in values) <= 2.0:
        x1 *= width
        x2 *= width
        y1 *= height
        y2 *= height
    left = int(max(0, min(width - 1, math.floor(min(x1, x2)))))
    top = int(max(0, min(height - 1, math.floor(min(y1, y2)))))
    right = int(max(0, min(width, math.ceil(max(x1, x2)))))
    bottom = int(max(0, min(height, math.ceil(max(y1, y2)))))
    if right - left < 12 or bottom - top < 12:
        return None
    return left, top, right, bottom


def _order_quad(points: np.ndarray) -> list[tuple[float, float]]:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    ordered = pts[np.argsort(angles)]
    start = int(np.argmin(ordered.sum(axis=1)))
    ordered = np.roll(ordered, -start, axis=0)
    return [(float(x), float(y)) for x, y in ordered]


def _angle_from_points(points: list[tuple[float, float]]) -> float | None:
    if len(points) != 4:
        return None
    (x0, y0), (x1, y1) = points[0], points[1]
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        return None
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


def refine_chip_obb_from_image(
    image_bgr: np.ndarray,
    detection: Detection,
    width: int,
    height: int,
) -> Detection:
    if detection.class_id != 0:
        return detection
    box = _box_to_pixels(detection, width, height)
    if box is None:
        return detection
    x1, y1, x2, y2 = box
    side = max(x2 - x1, y2 - y1)
    margin = max(18, int(round(side * 0.22)))
    rx1 = max(0, x1 - margin)
    ry1 = max(0, y1 - margin)
    rx2 = min(width, x2 + margin)
    ry2 = min(height, y2 + margin)
    roi = image_bgr[ry1:ry2, rx1:rx2]
    if roi.size == 0:
        return detection

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _threshold, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return detection

    search_area = float((rx2 - rx1) * (ry2 - ry1))
    box_area = float((x2 - x1) * (y2 - y1))
    best: tuple[float, np.ndarray] | None = None
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < max(160.0, box_area * 0.12) or area > search_area * 0.90:
            continue
        rect = cv2.minAreaRect(contour)
        (rect_w, rect_h) = rect[1]
        if rect_w < 20.0 or rect_h < 20.0:
            continue
        fill_ratio = area / max(1.0, rect_w * rect_h)
        if fill_ratio < 0.35:
            continue
        rank = area * fill_ratio
        if best is None or rank > best[0]:
            best = (rank, cv2.boxPoints(rect).astype(np.float32))
    if best is None:
        return detection

    points = best[1]
    points[:, 0] = np.clip(points[:, 0] + rx1, 0.0, float(width - 1))
    points[:, 1] = np.clip(points[:, 1] + ry1, 0.0, float(height - 1))
    ordered = _order_quad(points)
    if len(ordered) != 4 or polygon_area(ordered) <= 4.0:
        return detection

    xs = [point[0] for point in ordered]
    ys = [point[1] for point in ordered]
    detection.x1 = float(max(0.0, min(xs)))
    detection.y1 = float(max(0.0, min(ys)))
    detection.x2 = float(min(float(width - 1), max(xs)))
    detection.y2 = float(min(float(height - 1), max(ys)))
    detection.obb_points = ordered
    detection.contour = ordered
    detection.polygon = ordered
    detection.obb_angle = _angle_from_points(ordered)
    detection.area = polygon_area(ordered)
    return detection


def refine_chip_obbs_in_frame(image_bgr: np.ndarray, detections: list[Detection], width: int, height: int) -> list[Detection]:
    for detection in detections:
        refine_chip_obb_from_image(image_bgr, detection, width, height)
    return detections

from __future__ import annotations

import math

import cv2
import numpy as np

from .settings import ImageAdjustSettings


def _as_uint8_bgr(image: np.ndarray) -> np.ndarray:
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"expected BGR uint8 image, got shape={image.shape}")
    return image


def _apply_gamma(image: np.ndarray, gamma: float) -> np.ndarray:
    if math.isclose(gamma, 1.0, rel_tol=1e-3, abs_tol=1e-3):
        return image
    gamma = max(0.05, min(5.0, gamma))
    inv_gamma = 1.0 / gamma
    lut = np.array([((value / 255.0) ** inv_gamma) * 255.0 for value in range(256)], dtype=np.uint8)
    return cv2.LUT(image, lut)


def _apply_saturation(image: np.ndarray, saturation: float) -> np.ndarray:
    if math.isclose(saturation, 1.0, rel_tol=1e-3, abs_tol=1e-3):
        return image
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * max(0.0, saturation), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _apply_clahe(image: np.ndarray, clip_limit: float) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=max(0.1, clip_limit), tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    return cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)


def _apply_sharpness(image: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0:
        return image
    blur = cv2.GaussianBlur(image, (0, 0), sigmaX=1.2)
    return cv2.addWeighted(image, 1.0 + amount, blur, -amount, 0)


def apply_adjustments(image: np.ndarray, settings: ImageAdjustSettings) -> np.ndarray:
    """Return a processed preview image without mutating the capture source."""
    result = _as_uint8_bgr(image).copy()

    if settings.denoise > 0:
        strength = max(1, min(30, settings.denoise))
        result = cv2.fastNlMeansDenoisingColored(result, None, strength, strength, 7, 21)

    if not math.isclose(settings.contrast, 1.0, rel_tol=1e-3, abs_tol=1e-3) or settings.brightness != 0:
        result = cv2.convertScaleAbs(result, alpha=max(0.0, settings.contrast), beta=settings.brightness)

    result = _apply_gamma(result, settings.gamma)
    result = _apply_saturation(result, settings.saturation)

    if settings.clahe_enabled:
        result = _apply_clahe(result, settings.clahe_clip_limit)

    return _apply_sharpness(result, settings.sharpness)

"""`DESKEW` — contour-based skew correction (deep-dive §4.5), new for V3.

V2's fixed 8-variant sweep never included any rotation correction at all. Worth building for
real: this project's actual input medium is predominantly phone photos of receipts, not flatbed
scans, and a tilted receipt in-frame is an extremely common failure mode a tonal sweep does
nothing to address.

Hough-line-based skew detection is a real, named alternative (`§4.5`'s own bench-comparison
note) — not built here. Contour-based is the simpler default to start from since a receipt
photographed against a contrasting background/table surface gives a clean outer contour to work
from; whether that assumption holds against this project's own real receipts is exactly what
§11's bench case is for, not something to assume settled by this module alone.
"""

from __future__ import annotations

import cv2
import numpy as np

from .base import VariantGenerator, get_shape, to_gray

__all__ = ["deskew"]


def deskew(image: np.ndarray) -> np.ndarray:
    """Threshold, find the largest contour (the receipt itself against the background), fit a
    minimum-area bounding rectangle, use its angle to correct rotation.

    Returns the image **unchanged** when no contour is found (a blank or near-uniform image) —
    a `VariantGenerator` never raises for a degenerate input; `generation.py`'s own worker
    boundary is the only place a genuine exception becomes a `Variant.error`.

    Confirmed live against a real `cv2.UMat` input: `cv2.findContours` genuinely runs on
    `UMat` and returns real contours — only the `.shape` read needed `get_shape` (`UMat` has no
    `.shape` at all, same gap `to_gray` documents).
    """
    gray = to_gray(image)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image

    largest = max(contours, key=cv2.contourArea)
    angle = cv2.minAreaRect(largest)[-1]

    # minAreaRect's angle convention needs normalizing to a -45..45 range before use — a
    # well-known OpenCV gotcha, not a trivial pass-through: the raw value is otherwise liable to
    # rotate the image roughly 90 degrees the wrong way for a receipt already close to upright.
    if angle < -45:
        angle = 90 + angle

    h, w = get_shape(gray)
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )

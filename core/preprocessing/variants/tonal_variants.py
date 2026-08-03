"""Tonal variants (deep-dive §4.1-4.3): `STANDARD`, `BW_THRESHOLD`, `LOW_CONTRAST`,
`HIGH_CONTRAST`, and the trivial `COLOR` pass-through.

Every generator here returns a **grayscale** (or, for `COLOR`, unmodified) image — matching
§4's own sketches exactly, including the specific reason each technique was chosen over a
simpler alternative (a fixed threshold, a flat contrast multiplier): every choice below is
reasoned in the deep-dive, not just implemented from a code sketch.

Parametrized generators (`HIGH_CONTRAST`'s CLAHE clip limit/tile grid, `LOW_CONTRAST`'s alpha)
are built via a factory function taking the config value and returning a configured
`VariantGenerator` closure — `variant_registry.py` is what actually reads config and calls
these factories; the functions here stay ignorant of where a config value came from.

**`STANDARD` cannot run on `cv2.UMat`, confirmed directly, not assumed.** Its own percentile
stretch is genuine `numpy` array arithmetic (`np.percentile`, float subtraction) — §6.1's own
"transparent... falls back to CPU when a given op has no OpenCL implementation" framing is
about individual `cv2.*` calls, not arbitrary numpy code, and `numpy` simply cannot operate on
a `UMat` at all (`np.percentile(umat, ...)` raises `TypeError` — checked live, not assumed).
`standard()` pulls a `UMat` input back to a plain array via `.get()` before its own numpy work,
which is the honest, correct handling: this one variant's own algorithm has no OpenCL
acceleration path, on this or any future OpenCV version, not a gap to paper over.
"""

from __future__ import annotations

import cv2
import numpy as np

from .base import VariantGenerator, to_gray

__all__ = [
    "bw_threshold",
    "color",
    "high_contrast_factory",
    "low_contrast_factory",
    "standard",
]


def standard(image: np.ndarray) -> np.ndarray:
    """§4.1 — grayscale + percentile-clip autocontrast, deliberately mild.

    OpenCV has no direct PIL-autocontrast equivalent; a 1st/99th-percentile clip and normalize
    is the standard technique for the same effect — stretch the histogram to the full 0-255
    range while clipping extreme outlier pixels rather than the true min/max, which a single
    hot/dark pixel would otherwise distort. Stays deliberately mild because Tesseract's own
    Otsu step already handles uneven lighting better than aggressive preprocessing done before
    it sees the image (OCR deep-dive §4 — the reasoning this variant is built to respect, not
    duplicate).
    """
    gray = to_gray(image)
    if isinstance(gray, cv2.UMat):
        gray = gray.get()  # see this module's own docstring — no OpenCL path for numpy math
    lo, hi = np.percentile(gray, (1, 99))
    stretched = np.clip(
        (gray.astype(np.float32) - lo) * 255.0 / max(hi - lo, 1e-6), 0, 255
    ).astype(np.uint8)
    return stretched


def bw_threshold(image: np.ndarray) -> np.ndarray:
    """§4.2 — Otsu binarization: the optimal threshold computed *per image* from its own
    histogram, not a fixed cutoff picked once and applied regardless of lighting.

    Not redundant with Tesseract's own internal Otsu step (OCR deep-dive §4.2) — this is an
    independent estimate, useful for engines in the enabled set (RapidOCR, PaddleOCR) whose
    detector models expect a more standard input range and do not binarize internally the way
    Tesseract does.
    """
    gray = to_gray(image)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw


def low_contrast_factory(alpha: float = 0.6) -> VariantGenerator:
    """§4.3 — a simple linear scale, deliberately *not* CLAHE-tuned-down: this variant's own
    purpose is recovering text on receipts that are already over-exposed/blown-out, where
    CLAHE's local adaptivity does not help (there is no local contrast left to adapt to in a
    genuinely blown-out region)."""

    def _low_contrast(image: np.ndarray) -> np.ndarray:
        gray = to_gray(image)
        return cv2.convertScaleAbs(gray, alpha=alpha, beta=0)

    return _low_contrast


def high_contrast_factory(
    clip_limit: float = 2.0, tile_grid_size: tuple[int, int] = (8, 8)
) -> VariantGenerator:
    """§4.3 — CLAHE over a flat multiplier: operates on local neighborhoods rather than the
    whole image at once, so it does not blow out already-bright regions while boosting
    genuinely dim ones — a meaningfully better fit than a flat multiplier for a photographed
    receipt with uneven lighting across its length (a common failure mode for phone photos,
    distinct from a flatbed scan)."""

    def _high_contrast(image: np.ndarray) -> np.ndarray:
        gray = to_gray(image)
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
        return clahe.apply(gray)

    return _high_contrast


def color(image: np.ndarray) -> np.ndarray:
    """§3's `COLOR` — unmodified color pass-through, kept as a named kind for uniform
    handling alongside every other variant rather than a special-cased "no variant" branch at
    every call site."""
    return image

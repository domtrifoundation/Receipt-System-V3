"""`DENOISE` — a candidate, not a default (deep-dive §4.6).

Genuinely useful for grainy/low-light phone photos, but `fastNlMeansDenoising` is one of the
more expensive classical CV operations in this set — opt-in via config
(`variant_registry.py`'s own `enabled` flag), not default-on, until a real bench cost figure
exists to justify the extra processing time by default.
"""

from __future__ import annotations

import cv2
import numpy as np

from .base import VariantGenerator, to_gray

__all__ = ["denoise_factory"]


def denoise_factory(h: float = 10.0) -> VariantGenerator:
    def _denoise(image: np.ndarray) -> np.ndarray:
        # Confirmed live: cv2.fastNlMeansDenoising runs directly on cv2.UMat in this OpenCV
        # build, no CPU fallback needed here — checked rather than assumed, since §6.1's own
        # "falls back to CPU when a given op has no OpenCL implementation" framing means this
        # genuinely varies op by op (standard()'s own numpy percentile work has no such path
        # at all; this one does).
        return cv2.fastNlMeansDenoising(to_gray(image), h=h, templateWindowSize=7, searchWindowSize=21)

    return _denoise

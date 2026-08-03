"""Per-channel boost variants (deep-dive §4.4): `CHANNEL_BOOST_RED/GREEN/BLUE`.

Each produces its own single-channel variant image — isolating and boosting one color channel
can recover text that is low-contrast in the combined grayscale conversion but genuinely
distinct in one channel (e.g. faded blue ink against a white background).

**OpenCV's native channel order is BGR, not RGB** — an easy, real mistake to make porting from
PIL — flagged explicitly in the deep-dive and worth repeating here at the one place it would
actually bite: `cv2.split(image)` returns `(b, g, r)`, in that order, not `(r, g, b)`.
"""

from __future__ import annotations

import cv2
import numpy as np

from .base import VariantGenerator

__all__ = ["channel_boost_factory"]


def channel_boost_factory(channel: str, alpha: float = 1.6) -> VariantGenerator:
    """`channel` is `"red"`, `"green"`, or `"blue"` — resolved once at registration time
    (`variant_registry.py`), not re-parsed on every call."""
    if channel not in ("red", "green", "blue"):
        raise ValueError(f"channel must be 'red', 'green', or 'blue', got {channel!r}")
    # cv2.split's own return order is (b, g, r) — OpenCV's native BGR, not RGB.
    index = {"blue": 0, "green": 1, "red": 2}[channel]

    def _channel_boost(image: np.ndarray) -> np.ndarray:
        # `cv2.UMat` has no `.ndim`/`.shape` at all (confirmed directly, see `base.to_gray`'s
        # own docstring), so dimensionality here is checked via `cv2.split`'s own return length
        # rather than an attribute a UMat cannot provide. Confirmed directly, not assumed:
        # `cv2.split` on an already-single-channel image does NOT raise — it returns a
        # one-element tuple, which an unchecked `channels[index]` for index 1 or 2 would raise
        # IndexError on, and for index 0 would silently return the one channel regardless of
        # which color was actually requested.
        channels = cv2.split(image)
        if len(channels) == 1:
            # Already single-channel (e.g. handed a grayscale variant by mistake) — nothing
            # meaningful to "boost the red channel of" here; return it boosted as-is rather
            # than raise or silently mislabel it, matching every generator's own
            # tolerate-degraded-input posture.
            return cv2.convertScaleAbs(channels[0], alpha=alpha, beta=0)
        return cv2.convertScaleAbs(channels[index], alpha=alpha, beta=0)

    return _channel_boost

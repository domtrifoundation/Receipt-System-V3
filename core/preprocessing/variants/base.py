"""`VariantGenerator` — the `Protocol` every variant module implements (deep-dive §2).

Each generator is a plain function taking a decoded BGR `numpy.ndarray` (already loaded off the
process-pool boundary — see `generation.py` §8.4's own reasoning for why an image *reference*
crosses that boundary, never raw pixel bytes) and returning the transformed array. Generators
never touch the blob store, never see a `BlobRef`, and never raise — a technique that cannot
produce a sane result for a given input (`DESKEW` finding no contours on a blank image, for
instance) returns the *input unchanged* rather than raising; `generation.py`'s own worker
wrapper is what converts a genuine exception into a `Variant.error`, matching every other
API's identical "the boundary catches, the internals stay simple" convention.
"""

from __future__ import annotations

from typing import Protocol

import cv2
import numpy as np

__all__ = ["VariantGenerator", "get_shape", "to_gray"]


class VariantGenerator(Protocol):
    def __call__(self, image: np.ndarray) -> np.ndarray: ...


def to_gray(image: np.ndarray) -> np.ndarray:
    """BGR -> grayscale, tolerating an already-grayscale input — and, critically, working
    identically whether `image` is a plain `numpy.ndarray` or a `cv2.UMat` (§6.1's hardware
    path). `cv2.UMat` has no `.ndim`/`.shape` at all (confirmed directly — its own attribute
    list is `context, get, handle, isContinuous, isSubmatrix, offset, queue`, nothing else), so
    the usual `if image.ndim == 2` dimensionality check that works for a plain ndarray simply
    cannot be asked of a UMat. Attempting the conversion and catching the one real failure mode
    (a 2D/already-grayscale input, which `COLOR_BGR2GRAY` cannot be applied to) works uniformly
    for both — this is the one place that distinction is handled, not duplicated per generator.
    """
    try:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    except cv2.error:
        return image


def get_shape(image: np.ndarray) -> tuple[int, int]:
    """`(height, width)` for a plain `numpy.ndarray` or a `cv2.UMat` — `cv2.UMat` has no
    `.shape` at all (confirmed directly, same gap `to_gray` documents), so a `UMat` input's
    size is read via a single `.get()` copy-back rather than an attribute it does not have.
    `findContours`, `warpAffine` and friends run natively on `UMat` and do not need this — it
    exists only for the metadata calls (`warpAffine`'s own output-size argument, for one) that
    need plain integers, not a Mat handle."""
    if isinstance(image, cv2.UMat):
        return image.get().shape[:2]
    return image.shape[:2]

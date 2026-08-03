"""Panorama/stitching mode — deliberately server-side (deep-dive §4.3.2). The client
captures and uploads individual raw frames; the actual stitching happens here, using
native OpenCV's `cv2.Stitcher` (the full desktop/server build, not the WASM one the
in-browser single-photo perspective-correction step uses), giving access to more robust
feature-matching/blending than a browser build would reasonably carry.

`cv2.Stitcher.stitch()` is a genuinely blocking, CPU-bound native call — dispatched via
`run_in_executor`, the one exception to this whole API's otherwise fully-`async`,
I/O-bound shape (deep-dive §7.1).

`cv2.Stitcher`'s own status codes distinguish real failure reasons (`ERR_NEED_MORE_IMGS`,
`ERR_HOMOGRAPHY_EST_FAIL`, `ERR_CAMERA_PARAMS_ADJUST_FAIL`) — surfaced to the caller as
the specific `StitchFailed.status_code` rather than a flat "stitching failed," since "need
more images" and "bad match, retake this section" call for genuinely different
user-facing guidance (deep-dive §4.3.2).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ...errors import StitchFailed

if TYPE_CHECKING:
    # Type-only — `from __future__ import annotations` already defers every annotation
    # below to a string, so this import never needs to happen at runtime at all. A bare
    # top-level `import numpy as np` here (this module's own original form) broke
    # `forward_compat` collection on both 3.14 and 3.15: numpy isn't in `noxfile.py`'s
    # own narrow `FORWARD_COMPAT_DEPS` list, and this module doesn't otherwise need numpy
    # itself — every actual numpy call in this file happens inside `capture_session.py`'s
    # own lazily-imported `cv2`/`numpy` usage, not here.
    import numpy as np

__all__ = ["stitch_panorama"]


def _stitch_sync(frames: list[np.ndarray]) -> np.ndarray:
    import cv2

    stitcher = cv2.Stitcher.create(cv2.Stitcher_PANORAMA)
    status, result = stitcher.stitch(frames)
    if status != cv2.Stitcher_OK:
        raise StitchFailed(status)
    return result


async def stitch_panorama(frames: tuple[np.ndarray, ...]) -> np.ndarray:
    """Raises `StitchFailed` (carrying the real `cv2.Stitcher` status code) on any
    non-`Stitcher_OK` result — never returns a partial/best-effort image silently."""
    if len(frames) < 2:
        raise StitchFailed(-1, "at least two frames are required to stitch a panorama")

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _stitch_sync, list(frames))

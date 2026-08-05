"""`OcrEngine` — the `Protocol` every engine adapter implements (deep-dive §4, §6).

Every adapter's own third-party import lives *inside* the adapter module, resolved lazily
at `is_available()`/`read()` call time rather than at module import time
(`docs/PRINCIPLES.md` §3.3 point 5) — a missing optional dependency degrades that one
engine to unavailable, it never fails the whole registry at process start (§4.4).

`read()` never raises across the engine boundary either: `engine_registry.py` is the one
place an `OcrInternalError` subclass gets caught and turned into a failed `EngineReading`,
mirroring `core/preprocessing/generation.py`'s single conversion point. An adapter is free
to raise internally — that's the whole point of `errors.py`'s exception taxonomy — but it
must not catch broadly and swallow, since a genuinely unexpected exception is exactly what
`OcrEngineCrashed` exists to carry forward with its real detail, not paraphrase away.
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

from ..contracts import EngineName, EngineReading, TextRegion

__all__ = ["OcrEngine", "decode_image_dims", "quad_to_region", "timed_reading"]


@runtime_checkable
class OcrEngine(Protocol):
    @property
    def engine(self) -> EngineName: ...

    async def is_available(self) -> bool: ...

    async def read(self, image_bytes: bytes) -> EngineReading: ...


def timed_reading(
    start: float, engine: EngineName, text: str, **kwargs
) -> EngineReading:
    """`EngineReading` construction with `duration_ms` computed from a `time.monotonic()`
    start — the one bit of bookkeeping every adapter's success path needs, factored out so
    it's computed the same way everywhere rather than copy-pasted eight times."""
    duration_ms = int((time.monotonic() - start) * 1000)
    return EngineReading(engine=engine, text=text, duration_ms=duration_ms, **kwargs)


def decode_image_dims(image_bytes: bytes) -> tuple[int, int]:
    """`(width, height)` of an already-rasterized image — needed by every region-capable
    local engine (RapidOCR, PaddleOCR) to normalize a pixel-space quad box against
    `TextRegion.box`'s dimension-independent `(x, y, w, h)` shape (§3)."""
    import cv2
    import numpy as np

    array = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if array is None:
        return (0, 0)
    height, width = array.shape[:2]
    return (width, height)


def quad_to_region(quad, text: str, score: float, width: int, height: int) -> TextRegion:
    """Reduces a four-corner-point quad box (RapidOCR's and PaddleOCR's own native output
    shape) to `TextRegion`'s normalized bounding box — shared because both engines produce
    the same quad shape, only wrapped in a different outer tuple/list structure."""
    xs = [point[0] for point in quad]
    ys = [point[1] for point in quad]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if width <= 0 or height <= 0:
        return TextRegion(text=text, confidence=float(score), box=(0.0, 0.0, 0.0, 0.0))
    box = (x_min / width, y_min / height, (x_max - x_min) / width, (y_max - y_min) / height)
    return TextRegion(text=text, confidence=float(score), box=box)

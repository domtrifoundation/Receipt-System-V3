"""Tier 2 — RapidOCR (deep-dive §4.3).

`RapidOCR()(image_bytes)` is a blocking C++-backed call (detector + recognizer, ONNX
Runtime underneath) that already releases the GIL during its own native compute (deep-dive
§10.2's "Native/GIL-released" bucket) — dispatched here via `loop.run_in_executor`, which
gets real thread-level parallelism today on a standard GIL build, not just on 3.14t/3.15.

Per-region output is standardized (`contracts.TextRegion`) rather than RapidOCR-specific
(deep-dive §4.3's decision): RapidOCR's own result shape is a `(quad_box, text, score)`
triple per detected region, where `quad_box` is four `(x, y)` corner points (not an
axis-aligned rect) — this adapter reduces that quad to `(x, y, w, h)` via its own bounding
box and normalizes against the image's real pixel dimensions, since `TextRegion.box` is
defined dimension-independent (§3).

**`RapidOCR()` is a cached, lazily-constructed module-level singleton, not built fresh per
call.** Confirmed live against real hardware: constructing `RapidOCR()` itself is cheap
(~0.5s), but the *first* inference call pays a real one-time model-load cost (~13s on this
machine) that a fresh instance re-pays every time; a warm, reused instance's steady-state
inference is ~5s instead. Rebuilding per call was the original implementation here and it
made a real end-to-end registry test time out against the default 15-second per-engine
budget — not a hypothetical concern. A `threading.Lock` guards first construction since
`loop.run_in_executor`'s default pool runs multiple worker threads concurrently.
"""

from __future__ import annotations

import asyncio
import threading
import time

from ..contracts import EngineName, EngineReading
from .base import decode_image_dims, quad_to_region, timed_reading

__all__ = ["RapidOcrConfig", "RapidOcrEngine"]

_instance_lock = threading.Lock()
_cached_instance = None


def _get_rapidocr_instance():
    global _cached_instance
    if _cached_instance is None:
        with _instance_lock:
            if _cached_instance is None:
                from rapidocr_onnxruntime import RapidOCR

                _cached_instance = RapidOCR()
    return _cached_instance


class RapidOcrConfig:
    """A real config object (not a frozen dataclass — see `providers` below) rather than a
    bare `list[str]` parameter, so `engine_registry.py` has one consistent shape to build
    every engine's config from."""

    def __init__(self, providers: tuple[str, ...] = ("cpu",)) -> None:
        #: Ordered execution-provider preference (deep-dive §5.1/§5.7), e.g.
        #: `("openvino", "cpu")` or `("cuda", "cpu")`. RapidOCR's own high-level wrapper
        #: does not currently expose a `providers=[...]` passthrough (confirmed against
        #: the installed version's `__call__` signature) — stored here so the day that
        #: changes, this is the one place to wire it through, rather than left unrecorded.
        self.providers = providers


def _run_rapidocr(image_bytes: bytes, providers: tuple[str, ...]) -> tuple[list, float]:
    ocr = _get_rapidocr_instance()
    result, elapse = ocr(image_bytes)
    return (result or [], elapse[-1] if elapse else 0.0)


class RapidOcrEngine:
    def __init__(self, config: RapidOcrConfig | None = None) -> None:
        self._config = config or RapidOcrConfig()

    @property
    def engine(self) -> EngineName:
        return EngineName.RAPIDOCR

    async def is_available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        loop = asyncio.get_running_loop()
        raw, _device_elapse = await loop.run_in_executor(
            None, _run_rapidocr, image_bytes, self._config.providers
        )
        width, height = await loop.run_in_executor(None, decode_image_dims, image_bytes)

        regions = tuple(
            quad_to_region(quad, text, score, width, height) for quad, text, score in raw
        )
        merged_text = "\n".join(region.text for region in regions)
        mean_confidence = (
            sum(r.confidence for r in regions) / len(regions) if regions else None
        )
        return timed_reading(
            start, self.engine, merged_text, regions=regions, mean_confidence=mean_confidence
        )

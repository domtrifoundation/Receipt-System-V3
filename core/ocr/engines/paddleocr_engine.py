"""Tier 2 — PaddleOCR (deep-dive §4.4).

Heaviest local engine, not PyTorch — PaddlePaddle is Baidu's own independent deep learning
framework (`paddlepaddle`/`paddlepaddle-gpu`) plus `paddleocr` itself. `PaddleOCR` produces
per-region output natively, same shape decision as RapidOCR (§4.3): a quad box, text and
score per detected region, reduced to `TextRegion`'s normalized `(x, y, w, h)` via
`engines/base.py`'s shared `quad_to_region()` — the two engines are independent Provider
Registry entries with no special-casing between them (§4.4's own resolved question).

Like every optional engine here, the `paddleocr` import lives inside the methods that need
it, never at module load — an install without PaddlePaddle degrades this one engine to
unavailable, paying zero cost otherwise (`docs/PRINCIPLES.md` §3.3 point 5, §4.4).

**`PaddleOCR(...)` is a cached, lazily-constructed module-level singleton, per-language,
the same as `rapidocr_engine.py`'s own `_get_rapidocr_instance()`** — reasoned by direct
analogy to that engine's own confirmed one-time model-load cost, not independently
re-verified here (PaddlePaddle is not installed in this development environment; this is
the heaviest local engine and deliberately off by default, §4.4/§6). If PaddleOCR's own
one-time load cost turns out to be smaller or larger than RapidOCR's in practice, that's a
bench-suite finding to feed back into this file's own timeout/caching assumptions, not
something to leave unguarded on the strength of an analogy alone.
"""

from __future__ import annotations

import asyncio
import threading
import time

from ..contracts import EngineName, EngineReading
from .base import decode_image_dims, quad_to_region, timed_reading

__all__ = ["PaddleOcrConfig", "PaddleOcrEngine"]

_instance_lock = threading.Lock()
_cached_instances: dict[str, object] = {}


def _get_paddleocr_instance(lang: str):
    if lang not in _cached_instances:
        with _instance_lock:
            if lang not in _cached_instances:
                from paddleocr import PaddleOCR

                _cached_instances[lang] = PaddleOCR(lang=lang, use_angle_cls=True, show_log=False)
    return _cached_instances[lang]


class PaddleOcrConfig:
    def __init__(self, device: str = "cpu", lang: str = "en") -> None:
        #: `"cpu"` or `"cuda"` (deep-dive §5.2) — PaddlePaddle's own GPU path is a separate
        #: pip package (`paddlepaddle-gpu`), not a runtime flag, so this only selects which
        #: already-installed build's device the wrapper should use.
        self.device = device
        self.lang = lang


def _run_paddleocr(image_bytes: bytes, lang: str) -> list:
    import cv2
    import numpy as np

    ocr = _get_paddleocr_instance(lang)
    array = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    result = ocr.ocr(array, cls=True)
    return result[0] if result and result[0] else []


class PaddleOcrEngine:
    def __init__(self, config: PaddleOcrConfig | None = None) -> None:
        self._config = config or PaddleOcrConfig()

    @property
    def engine(self) -> EngineName:
        return EngineName.PADDLEOCR

    async def is_available(self) -> bool:
        try:
            import paddleocr  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, _run_paddleocr, image_bytes, self._config.lang)
        width, height = await loop.run_in_executor(None, decode_image_dims, image_bytes)

        # PaddleOCR's own per-line shape: `[quad_box, (text, score)]`.
        regions = tuple(
            quad_to_region(quad, text, score, width, height) for quad, (text, score) in raw
        )
        merged_text = "\n".join(region.text for region in regions)
        mean_confidence = (
            sum(r.confidence for r in regions) / len(regions) if regions else None
        )
        return timed_reading(
            start, self.engine, merged_text, regions=regions, mean_confidence=mean_confidence
        )

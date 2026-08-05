"""Tier 2 — PaddleOCR (deep-dive §4.4, §5.2 for hardware).

Heaviest local engine, not PyTorch — PaddlePaddle is Baidu's own independent deep learning
framework (`paddlepaddle`/`paddlepaddle-gpu`) plus `paddleocr` itself. `PaddleOCR` produces
per-region output natively, same shape decision as RapidOCR (§4.3): a quad box, text and
score per detected region, reduced to `TextRegion`'s normalized `(x, y, w, h)` via
`engines/base.py`'s shared `quad_to_region()` — the two engines are independent Provider
Registry entries with no special-casing between them (§4.4's own resolved question).

Like every optional engine here, the `paddleocr` import lives inside the methods that need
it, never at module load — an install without PaddlePaddle degrades this one engine to
unavailable, paying zero cost otherwise (`docs/PRINCIPLES.md` §3.3 point 5, §4.4).

**`PaddleOCR(...)` is a cached, lazily-constructed singleton, keyed by `(lang, use_gpu)`,
the same as `rapidocr_engine.py`'s own `_get_rapidocr_instance()`** — reasoned by direct
analogy to that engine's own confirmed one-time model-load cost, not independently
re-verified here (PaddlePaddle is not installed in this development environment; this is
the heaviest local engine and deliberately off by default, §4.4/§6).

**The GPU device kwarg passed to `PaddleOCR(...)` is NOT independently verified this
session** — PaddleOCR's own constructor kwarg for GPU selection has genuinely changed
across major releases (`use_gpu: bool` on the ~2.x line most of the ecosystem still runs,
versus `device: "gpu"|"cpu"` on the newer PaddleX-based 3.x line) and PaddlePaddle is not
installed here to check which one a real install would actually need. `use_gpu` is used
below as the more broadly-applicable choice today, flagged honestly rather than asserted —
the same posture `backends/onnx_genai_backend.py`'s own module docstring takes for its own
unverified library call shape. Gated on a real Health API VRAM reservation (deep-dive
§5.6) exactly like RapidOCR's own `use_cuda` gate, not requested unconditionally.
"""

from __future__ import annotations

import asyncio
import threading
import time

from ..contracts import EngineName, EngineReading
from ..health_client import HealthClient
from .base import decode_image_dims, quad_to_region, timed_reading

__all__ = ["PaddleOcrConfig", "PaddleOcrEngine"]

_instance_lock = threading.Lock()
_cached_instances: dict[tuple[str, bool], object] = {}


def _get_paddleocr_instance(lang: str, use_gpu: bool):
    key = (lang, use_gpu)
    if key not in _cached_instances:
        with _instance_lock:
            if key not in _cached_instances:
                from paddleocr import PaddleOCR

                _cached_instances[key] = PaddleOCR(
                    lang=lang, use_angle_cls=True, show_log=False, use_gpu=use_gpu
                )
    return _cached_instances[key]


class PaddleOcrConfig:
    def __init__(
        self,
        device: str = "cpu",
        lang: str = "en",
        device_id: str = "gpu0",
        estimated_vram_mb: int = 500,
    ) -> None:
        #: `"cpu"` or `"cuda"` (deep-dive §5.2) — PaddlePaddle's own GPU path is a separate
        #: pip package (`paddlepaddle-gpu`), not a runtime flag, so this only selects which
        #: already-installed build's device the wrapper should use.
        self.device = device
        self.lang = lang
        self.device_id = device_id
        #: A reasoned placeholder (heaviest local engine, larger than RapidOCR's own
        #: estimate above it) — not a bench-measured figure; refine once the bench suite
        #: exists, same posture as every other unmeasured constant in this project.
        self.estimated_vram_mb = estimated_vram_mb


def _run_paddleocr(image_bytes: bytes, lang: str, use_gpu: bool) -> list:
    import cv2
    import numpy as np

    ocr = _get_paddleocr_instance(lang, use_gpu)
    array = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    result = ocr.ocr(array, cls=True)
    return result[0] if result and result[0] else []


class PaddleOcrEngine:
    def __init__(self, config: PaddleOcrConfig | None = None, health_client: HealthClient | None = None) -> None:
        self._config = config or PaddleOcrConfig()
        self._health_client = health_client or HealthClient()
        self._use_gpu_decision: bool | None = None
        self._reservation_id: str = ""

    @property
    def engine(self) -> EngineName:
        return EngineName.PADDLEOCR

    async def is_available(self) -> bool:
        try:
            import paddleocr  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def _resolve_use_gpu(self) -> bool:
        """Resolved once per engine instance, then cached — same reasoning as
        `RapidOcrEngine._resolve_use_cuda`'s own docstring."""
        if self._use_gpu_decision is not None:
            return self._use_gpu_decision
        if self._config.device != "cuda":
            self._use_gpu_decision = False
            return False

        outcome = await self._health_client.reserve(
            "ocr", self._config.device_id, self._config.estimated_vram_mb
        )
        self._use_gpu_decision = outcome.granted
        self._reservation_id = outcome.reservation_id
        return self._use_gpu_decision

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        use_gpu = await self._resolve_use_gpu()
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, _run_paddleocr, image_bytes, self._config.lang, use_gpu)
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
            start, self.engine, merged_text, regions=regions, mean_confidence=mean_confidence,
            device="cuda" if use_gpu else "cpu",
        )

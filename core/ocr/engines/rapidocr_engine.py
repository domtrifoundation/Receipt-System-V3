"""Tier 2 — RapidOCR (deep-dive §4.3, §5.1/§5.7 for hardware).

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

**`RapidOCR()` is a cached, lazily-constructed singleton, keyed by its actual EP decision
(`use_cuda`), not built fresh per call.** Confirmed live against real hardware:
constructing `RapidOCR()` itself is cheap (~0.5s), but the *first* inference call pays a
real one-time model-load cost (~13s on this machine) that a fresh instance re-pays every
time; a warm, reused instance's steady-state inference is ~5s instead. Rebuilding per call
was the original implementation here and it made a real end-to-end registry test time out
against the default 15-second per-engine budget — not a hypothetical concern. A
`threading.Lock` guards first construction since `loop.run_in_executor`'s default pool
runs multiple worker threads concurrently.

**§5.1's own full execution-provider list (CUDA/TensorRT/DirectML/OpenVINO/CoreML/
MIGraphX/QNN) is NOT achievable through this installed library version, checked directly
rather than assumed** — `rapidocr_onnxruntime`'s own `OrtInferSession` (confirmed by
reading its actual source, `rapidocr_onnxruntime/utils.py`) only ever builds an
`onnxruntime.InferenceSession` with a hardcoded `[CUDAExecutionProvider, CPUExecutionProvider]`
list gated on a single boolean `use_cuda` flag — there is no `providers=[...]` passthrough
for OpenVINO/DirectML/QNN/MIGraphX at all in this wrapper, at this version. This is exactly
the deep-dive's own named risk (§5.1: "worth confirming... since not every high-level OCR
wrapper surfaces this") — confirmed, and the honest answer is "only `use_cuda` exists,"
not "the full EP list is wired through." That one real lever (`det_use_cuda`/`cls_use_cuda`/
`rec_use_cuda` kwargs — confirmed live: passing them without a matching `*_model_path` key
raises `KeyError` in this version, a real, undocumented quirk) is wired below, gated on a
real Health API VRAM reservation (deep-dive §5.6) rather than blindly requested.
"""

from __future__ import annotations

import asyncio
import threading
import time

from ..contracts import EngineName, EngineReading
from ..health_client import HealthClient
from .base import decode_image_dims, quad_to_region, timed_reading

__all__ = ["RapidOcrConfig", "RapidOcrEngine"]

_instance_lock = threading.Lock()
_cached_instances: dict[bool, object] = {}


def _get_rapidocr_instance(use_cuda: bool):
    if use_cuda not in _cached_instances:
        with _instance_lock:
            if use_cuda not in _cached_instances:
                from rapidocr_onnxruntime import RapidOCR

                _cached_instances[use_cuda] = RapidOCR(
                    det_use_cuda=use_cuda, det_model_path=None,
                    cls_use_cuda=use_cuda, cls_model_path=None,
                    rec_use_cuda=use_cuda, rec_model_path=None,
                )
    return _cached_instances[use_cuda]


class RapidOcrConfig:
    """A real config object (not a frozen dataclass — see `device` below) rather than a
    bare `list[str]` parameter, so `engine_registry.py` has one consistent shape to build
    every engine's config from."""

    def __init__(
        self,
        providers: tuple[str, ...] = ("cpu",),
        device: str = "cpu",
        device_id: str = "gpu0",
        estimated_vram_mb: int = 200,
    ) -> None:
        #: Kept for documentation continuity with the deep-dive's own §5.7 config sketch
        #: (`rapidocr_providers: [openvino, cpu]`) — this wrapper cannot actually honor an
        #: ordered multi-EP list (see module docstring), so only `device`'s `"cuda"`/`"cpu"`
        #: distinction is load-bearing today.
        self.providers = providers
        #: `"cpu"` or `"cuda"` — the only EP lever this wrapper version genuinely exposes.
        self.device = device
        self.device_id = device_id
        #: A reasoned placeholder, not a bench-measured figure (same posture as Tesseract's
        #: PSM default, OCR deep-dive §9) — RapidOCR's det+cls+rec ONNX models are small;
        #: refine from real measurement once the bench suite exists.
        self.estimated_vram_mb = estimated_vram_mb


def _run_rapidocr(image_bytes: bytes, use_cuda: bool) -> tuple[list, float]:
    ocr = _get_rapidocr_instance(use_cuda)
    result, elapse = ocr(image_bytes)
    return (result or [], elapse[-1] if elapse else 0.0)


class RapidOcrEngine:
    def __init__(self, config: RapidOcrConfig | None = None, health_client: HealthClient | None = None) -> None:
        self._config = config or RapidOcrConfig()
        self._health_client = health_client or HealthClient()
        self._use_cuda_decision: bool | None = None
        self._reservation_id: str = ""

    @property
    def engine(self) -> EngineName:
        return EngineName.RAPIDOCR

    async def is_available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def _resolve_use_cuda(self) -> bool:
        """Resolved once per engine instance, then cached — a Health API reservation call
        on every single `read()` would be real, avoidable overhead for a decision that
        doesn't change mid-process. Deep-dive §5.6: reserve before allocating a GPU
        session, fall back to CPU on rejection rather than failing the engine."""
        if self._use_cuda_decision is not None:
            return self._use_cuda_decision
        if self._config.device != "cuda":
            self._use_cuda_decision = False
            return False

        outcome = await self._health_client.reserve(
            "ocr", self._config.device_id, self._config.estimated_vram_mb
        )
        self._use_cuda_decision = outcome.granted
        self._reservation_id = outcome.reservation_id
        return self._use_cuda_decision

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        use_cuda = await self._resolve_use_cuda()
        loop = asyncio.get_running_loop()
        raw, _device_elapse = await loop.run_in_executor(None, _run_rapidocr, image_bytes, use_cuda)
        width, height = await loop.run_in_executor(None, decode_image_dims, image_bytes)

        regions = tuple(
            quad_to_region(quad, text, score, width, height) for quad, text, score in raw
        )
        merged_text = "\n".join(region.text for region in regions)
        mean_confidence = (
            sum(r.confidence for r in regions) / len(regions) if regions else None
        )
        return timed_reading(
            start, self.engine, merged_text, regions=regions, mean_confidence=mean_confidence,
            device="cuda" if use_cuda else "cpu",
        )

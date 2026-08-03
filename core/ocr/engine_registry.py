"""`OcrEngineRegistry` — the Provider Registry mapping `EngineName` -> `OcrEngine` (deep-dive
§6). Every engine is independently enableable and, when more than one is requested, runs in
parallel — real corroboration value from *several* readings of the same image, unlike
Auth's own registry where exactly one provider is *used* per login (`core/auth/auth_methods/
base.py`'s own docstring draws that distinction explicitly; this registry is the other
shape of §1.2's rule).

**This is the one place an engine adapter's internal exception becomes a wire-facing
`EngineReading`** (mirroring `core/preprocessing/generation.py`'s single conversion point,
`errors.py`'s own module docstring). An adapter that raises anything else — a bare
`Exception` neither this package nor the adapter anticipated — still becomes an
`ENGINE_CRASHED` reading rather than propagating, since a genuinely unexpected native
failure from RapidOCR/PaddleOCR is exactly the "per-engine failures are expected, not
alarm-worthy" case the deep-dive names (§4.3).

**Cloud budget enforcement lives here, not in `cloud_engines/base_cloud_engine.py`**
(deep-dive §4.7's own stated ownership): a per-run, per-engine call counter, checked
*before* dispatching to the adapter at all, so a call past budget never reaches the
network.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field

from .contracts import (
    AgreementLevel,
    BlobStoreGateway,
    EngineName,
    EngineReading,
    OcrError,
    OcrErrorCode,
    OcrRequest,
    OcrResult,
)
from .corroboration import merge_readings
from .engines.apple_vision_engine import AppleVisionEngine
from .engines.base import OcrEngine
from .engines.cloud_engines.aws_textract import AwsTextractEngine
from .engines.cloud_engines.azure_doc_intelligence import AzureDocumentIntelligenceEngine
from .engines.cloud_engines.base_cloud_engine import CloudEngineConfig
from .engines.cloud_engines.google_vision import GoogleVisionEngine
from .engines.paddleocr_engine import PaddleOcrConfig, PaddleOcrEngine
from .engines.rapidocr_engine import RapidOcrConfig, RapidOcrEngine
from .engines.tesseract_engine import TesseractConfig, TesseractEngine
from .engines.text_layer_engine import TextLayerEngine
from .engines.windows_ocr_engine import WindowsOcrEngine
from .errors import (
    OcrAuthError,
    OcrBudgetExceeded,
    OcrEngineCrashed,
    OcrEnginePlatformUnsupported,
    OcrEngineTimeout,
    OcrEngineUnavailable,
    OcrInternalError,
    OcrNetworkError,
    OcrRateLimited,
)
from .health_client import HealthClient
from .metrics import OcrMetricsCollector

__all__ = ["OcrConfig", "OcrEngineRegistry"]

#: §6/§9's own reasoned starting set — text-layer extraction and Tesseract are always
#: cheap/free/offline; RapidOCR is light enough to include by default too. Everything
#: heavier, paid, or platform-limited (PaddleOCR, Windows OCR, Apple Vision, the cloud
#: tier) is opt-in, matching the deep-dive's own "off by default" framing for those.
DEFAULT_ENGINES_ENABLED: frozenset[EngineName] = frozenset(
    {EngineName.TEXT_LAYER, EngineName.TESSERACT, EngineName.RAPIDOCR}
)

#: Exception type -> wire error code. Checked in subclass-first order below since
#: `OcrEnginePlatformUnsupported`/`OcrBudgetExceeded` etc. do not themselves subclass one
#: another, but `isinstance` order still matters if that ever changes.
_ERROR_CODE_BY_EXCEPTION: tuple[tuple[type[OcrInternalError], OcrErrorCode], ...] = (
    (OcrEnginePlatformUnsupported, OcrErrorCode.ENGINE_PLATFORM_UNSUPPORTED),
    (OcrEngineUnavailable, OcrErrorCode.ENGINE_UNAVAILABLE),
    (OcrEngineTimeout, OcrErrorCode.ENGINE_TIMEOUT),
    (OcrBudgetExceeded, OcrErrorCode.BUDGET_EXCEEDED),
    (OcrNetworkError, OcrErrorCode.NETWORK_ERROR),
    (OcrAuthError, OcrErrorCode.AUTH_ERROR),
    (OcrRateLimited, OcrErrorCode.RATE_LIMITED),
    (OcrEngineCrashed, OcrErrorCode.ENGINE_CRASHED),
)


@dataclass(frozen=True)
class OcrConfig:
    """§6's config surface, as a real typed object rather than a loosely-shaped dict."""

    engines_enabled: frozenset[EngineName] = field(
        default_factory=lambda: DEFAULT_ENGINES_ENABLED
    )
    tesseract: TesseractConfig = field(default_factory=TesseractConfig)
    rapidocr: RapidOcrConfig = field(default_factory=RapidOcrConfig)
    paddleocr: PaddleOcrConfig = field(default_factory=PaddleOcrConfig)
    cloud_vision: CloudEngineConfig = field(default_factory=CloudEngineConfig)
    azure_document_intelligence: CloudEngineConfig = field(default_factory=CloudEngineConfig)
    aws_textract: CloudEngineConfig = field(default_factory=CloudEngineConfig)
    per_engine_timeout_ms: int = 15_000


def _wire_error(exc: Exception) -> OcrError:
    for exc_type, code in _ERROR_CODE_BY_EXCEPTION:
        if isinstance(exc, exc_type):
            return OcrError(code, str(exc))
    # An adapter raised something outside this package's own taxonomy entirely (a native
    # RapidOCR/PaddleOCR exception, for instance) — still a crash, not a propagated error.
    return OcrError(OcrErrorCode.ENGINE_CRASHED, f"{type(exc).__name__}: {exc}")


class OcrEngineRegistry:
    """Built once from an `OcrConfig` and a `BlobStoreGateway`. `available_engines()` is
    every engine this registry can structurally run at all, probed live; `enabled_engines()`
    is the `available ∩ config.engines_enabled` subset (the same shape
    `core/preprocessing/variant_registry.py`'s `VariantRegistry` uses for variant kinds)."""

    def __init__(
        self,
        config: OcrConfig | None = None,
        blob_store: BlobStoreGateway | None = None,
        metrics: OcrMetricsCollector | None = None,
        health_client: HealthClient | None = None,
    ) -> None:
        self._config = config or OcrConfig()
        self._blob_store = blob_store
        self._metrics = metrics
        #: One shared `HealthClient` for every GPU-capable engine — a real reservation
        #: call per engine instance, not per request (deep-dive §5.6).
        self._health_client = health_client or HealthClient()
        self._engines: dict[EngineName, OcrEngine] = {
            EngineName.TEXT_LAYER: TextLayerEngine(),
            EngineName.TESSERACT: TesseractEngine(self._config.tesseract),
            EngineName.RAPIDOCR: RapidOcrEngine(self._config.rapidocr, self._health_client),
            EngineName.PADDLEOCR: PaddleOcrEngine(self._config.paddleocr, self._health_client),
            EngineName.CLOUD_VISION: GoogleVisionEngine(self._config.cloud_vision),
            EngineName.AZURE_DOCUMENT_INTELLIGENCE: AzureDocumentIntelligenceEngine(
                self._config.azure_document_intelligence
            ),
            EngineName.AWS_TEXTRACT: AwsTextractEngine(self._config.aws_textract),
        }
        # Windows OCR / Apple Vision are platform-gated at construction, not omitted from
        # the dict entirely — a Linux install still lists them (as unavailable) rather
        # than the registry pretending they don't exist as a concept (deep-dive §4.5-§4.6).
        self._engines[EngineName.WINDOWS_OCR] = WindowsOcrEngine()
        self._engines[EngineName.APPLE_VISION] = AppleVisionEngine()

        #: `(run_id, engine)` -> calls made so far. A plain mutable dict guarded by a lock,
        #: not a `FrozenDict` — genuinely mutable runtime state, the same category
        #: `docs/PRINCIPLES.md` §2.1.1 excludes from the constant rule.
        self._cloud_call_counts: dict[tuple[str, EngineName], int] = {}
        self._cloud_lock = threading.Lock()

    def registered(self) -> tuple[EngineName, ...]:
        return tuple(self._engines)

    async def _one_availability(self, name: EngineName) -> bool:
        engine = self._engines.get(name)
        if engine is None:
            return False
        try:
            return await engine.is_available()
        except Exception:  # noqa: BLE001 - a probe failure means unavailable, not a crash
            return False

    async def available_engines(self) -> frozenset[EngineName]:
        names = tuple(self._engines)
        results = await asyncio.gather(*(self._one_availability(n) for n in names))
        return frozenset(name for name, available in zip(names, results) if available)

    async def enabled_engines(self) -> frozenset[EngineName]:
        available = await self.available_engines()
        return available & self._config.engines_enabled

    def _cloud_budget(self, name: EngineName) -> int | None:
        return {
            EngineName.CLOUD_VISION: self._config.cloud_vision.max_calls_per_run,
            EngineName.AZURE_DOCUMENT_INTELLIGENCE:
                self._config.azure_document_intelligence.max_calls_per_run,
            EngineName.AWS_TEXTRACT: self._config.aws_textract.max_calls_per_run,
        }.get(name)

    def _check_and_spend_budget(self, run_id: str, name: EngineName) -> bool:
        """Returns `True` if this call is within budget (and records it as spent) — `False`
        if the call must be refused before the network call happens."""
        budget = self._cloud_budget(name)
        if budget is None:
            return True
        with self._cloud_lock:
            key = (run_id, name)
            spent = self._cloud_call_counts.get(key, 0)
            if spent >= budget:
                return False
            self._cloud_call_counts[key] = spent + 1
        return True

    async def _read_one(
        self, run_id: str, name: EngineName, image_bytes: bytes, timeout_ms: int
    ) -> EngineReading:
        start = time.monotonic()
        engine = self._engines.get(name)
        if engine is None:
            return EngineReading.failure(
                name, OcrError(OcrErrorCode.ENGINE_UNAVAILABLE, "no provider registered")
            )

        if not self._check_and_spend_budget(run_id, name):
            if self._metrics is not None:
                self._metrics.increment("cloud_budget_exceeded_count")
            return EngineReading.failure(
                name, OcrError(OcrErrorCode.BUDGET_EXCEEDED, "per-run cloud call budget spent")
            )
        if self._cloud_budget(name) is not None and self._metrics is not None:
            self._metrics.increment("cloud_calls_made")

        try:
            reading = await asyncio.wait_for(engine.read(image_bytes), timeout=timeout_ms / 1000)
        except TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            reading = EngineReading.failure(
                name, OcrError(OcrErrorCode.ENGINE_TIMEOUT, f"exceeded {timeout_ms}ms"),
                duration_ms,
            )
        except Exception as exc:  # noqa: BLE001 - see module docstring: this is the boundary
            duration_ms = int((time.monotonic() - start) * 1000)
            reading = EngineReading.failure(name, _wire_error(exc), duration_ms)

        self._record_metrics(reading)
        return reading

    def _record_metrics(self, reading: EngineReading) -> None:
        if self._metrics is None or reading.error is None:
            return
        counter_by_code = {
            OcrErrorCode.ENGINE_UNAVAILABLE: "engine_unavailable_count",
            OcrErrorCode.ENGINE_PLATFORM_UNSUPPORTED: "engine_unavailable_count",
            OcrErrorCode.ENGINE_CRASHED: "engine_crashed_count",
            OcrErrorCode.ENGINE_TIMEOUT: "engine_timeout_count",
        }
        counter = counter_by_code.get(reading.error.code)
        if counter is not None:
            self._metrics.increment(counter)

    async def run(self, request: OcrRequest) -> OcrResult:
        """Fans out to every engine in `request.engines` concurrently — the caller's own
        choice of which engines to run, never a policy decision made here (deep-dive §1)."""
        if self._blob_store is None:
            error = OcrError(OcrErrorCode.BLOB_NOT_FOUND, "no blob store configured")
            readings = tuple(
                EngineReading.failure(name, error) for name in request.engines
            )
            return merge_readings(readings)

        try:
            image_bytes = await self._blob_store.read_blob(request.image_ref)
        except Exception as exc:  # noqa: BLE001 - a missing/unreadable blob fails every engine
            error = OcrError(OcrErrorCode.BLOB_NOT_FOUND, str(exc))
            readings = tuple(
                EngineReading.failure(name, error) for name in request.engines
            )
            return merge_readings(readings)

        # §6's own `per_engine_timeout_ms` config value is an administrator-set ceiling,
        # not merely a duplicate of `OcrRequest.timeout_ms`'s own contract default — a
        # real, complete gap until caught (a config field declared and read by nothing).
        # A caller's own per-request timeout can ask for *less* time, never more, than
        # what the operator configured for this install.
        effective_timeout_ms = min(request.timeout_ms, self._config.per_engine_timeout_ms)
        readings = await asyncio.gather(
            *(
                self._read_one(request.run_id, name, image_bytes, effective_timeout_ms)
                for name in request.engines
            )
        )
        result = merge_readings(tuple(readings))
        if self._metrics is not None:
            self._metrics.increment(
                "reads_succeeded" if result.agreement != AgreementLevel.NONE else "reads_failed"
            )
        return result

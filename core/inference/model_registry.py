"""`InferenceModelRegistry` — the Provider Registry mapping preset name -> `PresetWorker`
(deep-dive §6.2), with the real double-checked-locking pattern the deep-dive names
explicitly: one `asyncio.Lock` per preset name (not one global lock), so loading
`phi4-mini` and `phi4-vision` concurrently never serializes against each other just
because both happen to be "a model load."

This is also the one place a `GenerationRequest` is actually assembled into a real
`PresetWorker.submit()` call: resolving the effective preset, the constrained-decoding
schema (`structured_output.resolve_schema`), and any image content (`vision.resolve_images`)
all happen here, in Inference API's own parent process, before anything crosses to a
worker's child process — the same "the boundary catches, the internals stay simple"
convention `core/ocr/engine_registry.py` and `core/preprocessing/generation.py` both
already follow for their own domains.

**Model directory resolution here is deliberately simple, not the live Hugging Face
lookup `presets.resolve_variant_path()` performs.** Per-request generation must never make
a network call — resolving which exact variant folder to download is a one-time
provisioning step (Setup API's/Update API's own territory, run once when a preset is first
enabled), not something this registry re-derives on every `generate()` call. This registry
only ever joins `config.models_dir` with the preset name — the real provisioning path
populating that directory correctly is out of this module's own scope.
"""

from __future__ import annotations

import asyncio
import collections
import inspect
import os
import time
from dataclasses import dataclass, field, replace

from common.frozen_dict import FrozenDict

from .contracts import (
    GenerationRequest,
    GenerationResult,
    InferenceError,
    InferenceErrorCode,
)
from .errors import GenerationCrashed, GenerationTimeout, ModelLoadFailed, WorkerUnavailable
from .generation import PresetWorker, TruncationConfig
from .health_client import HealthClient
from .metrics import InferenceMetricsCollector
from .presets import MODEL_PRESETS, PresetSpec
from .structured_output import resolve_schema
from .vision import resolve_images

__all__ = ["InferenceConfig", "InferenceModelRegistry"]

DEFAULT_PRESETS_ENABLED: frozenset[str] = frozenset({"phi4-mini"})


@dataclass(frozen=True)
class InferenceConfig:
    """§10's config surface, as a real typed object."""

    presets_enabled: frozenset[str] = field(default_factory=lambda: DEFAULT_PRESETS_ENABLED)
    #: Resolves an empty `GenerationRequest.preset` (`generate()`'s own fallback below) —
    #: a real, enforced default, not just documentation.
    default_preset: str = "phi4-mini"
    #: Deliberately NOT read anywhere in this module's own runtime. §1's own design
    #: principle is "caller's choice, not policy" for every request this API serves —
    #: auto-substituting a vision-capable preset whenever a request happens to carry
    #: image content would be exactly the policy decision this API is built not to make.
    #: This value exists for *other* callers to read (Execution Core deciding which
    #: preset to request for a vision-corroboration step, Interface API's settings menu
    #: preselecting one) — declarative config this API's own schema carries, not a
    #: runtime behavior it enforces itself.
    vision_preset: str = "phi4-vision"
    device_by_preset: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    models_dir: str = "models"
    batch_window_ms: int = 30
    #: Queue depth cap before backpressure, per preset (§10) — the (N+1)th concurrent
    #: caller against one preset's worker waits for a free slot rather than piling an
    #: unbounded number of requests into that worker's own queue.
    max_concurrent_generations: int = 4
    reasoning_token_budget: int = 1024
    truncation_retry_multiplier: float = 2.0
    per_request_timeout_ms: int = 30_000


class InferenceModelRegistry:
    def __init__(
        self,
        config: InferenceConfig | None = None,
        blob_store=None,
        metrics: InferenceMetricsCollector | None = None,
        *,
        worker_factory=None,
        health_client: HealthClient | None = None,
    ) -> None:
        self._config = config or InferenceConfig()
        self._blob_store = blob_store
        self._metrics = metrics
        #: Defaults to real `PresetWorker` construction. Overridable so
        #: `tests/unit/core/inference/test_model_registry.py` can inject a fake-backed
        #: worker to exercise the real §6.2 lazy-load-locking race without real model
        #: weights — same seam shape as `generation.py`'s own `backend_factory`. May be
        #: sync or async; `get_worker()` awaits it only if it actually returned an
        #: awaitable, so existing sync test fakes keep working unchanged.
        self._worker_factory = worker_factory or self._default_worker
        self._health_client = health_client or HealthClient()
        self._loaded_workers: dict[str, PresetWorker] = {}
        self._reservations: dict[str, str] = {}
        self._load_locks: dict[str, asyncio.Lock] = collections.defaultdict(asyncio.Lock)

    async def _default_worker(self, preset_name: str) -> PresetWorker:
        """Resolves the real device to load on, gated on a real Health API VRAM
        reservation (deep-dive §8.6) — a GPU device configured but rejected by Health
        falls back to `"cpu"` for this worker rather than failing the load entirely."""
        spec = PresetSpec(preset_name)
        configured_device = self._device_for(preset_name)
        device = configured_device
        if configured_device != "cpu":
            outcome = await self._health_client.reserve(
                "inference", configured_device, spec.estimated_vram_mb
            )
            if outcome.granted:
                self._reservations[preset_name] = outcome.reservation_id
            else:
                device = "cpu"

        return PresetWorker(
            preset_name,
            self._model_dir_for(preset_name),
            device,
            batch_window_ms=self._config.batch_window_ms,
            truncation=TruncationConfig(retry_multiplier=self._config.truncation_retry_multiplier),
            reasoning_marker=spec.reasoning_marker,
            reasoning_token_budget=self._config.reasoning_token_budget,
            max_concurrent_generations=self._config.max_concurrent_generations,
        )

    def _device_for(self, preset_name: str) -> str:
        return self._config.device_by_preset.get(preset_name, "cpu")

    def _model_dir_for(self, preset_name: str) -> str:
        return os.path.join(self._config.models_dir, preset_name)

    async def get_worker(self, preset_name: str) -> PresetWorker:
        """The deep-dive's own §6.2 double-checked-locking pattern, verbatim in shape."""
        if preset_name in self._loaded_workers:
            return self._loaded_workers[preset_name]
        async with self._load_locks[preset_name]:
            if preset_name in self._loaded_workers:
                return self._loaded_workers[preset_name]
            result = self._worker_factory(preset_name)
            worker = await result if inspect.isawaitable(result) else result
            await worker.load()
            self._loaded_workers[preset_name] = worker
            return worker

    def available_presets(self) -> frozenset[str]:
        return frozenset(MODEL_PRESETS)

    def enabled_presets(self) -> frozenset[str]:
        return self.available_presets() & self._config.presets_enabled

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        start = time.monotonic()
        # §10's own `default_preset` config value: an empty `request.preset` resolves to
        # it rather than failing as an unconfigured preset — this was a real, complete
        # gap until caught (a config field declared and read by nothing).
        preset_name = request.preset or self._config.default_preset
        if preset_name not in self.enabled_presets():
            self._record_failure(InferenceErrorCode.PRESET_NOT_CONFIGURED)
            return GenerationResult.failure(
                InferenceError(
                    InferenceErrorCode.PRESET_NOT_CONFIGURED,
                    f"preset {preset_name!r} is not configured/enabled",
                )
            )
        if preset_name != request.preset:
            request = replace(request, preset=preset_name)

        spec = PresetSpec(preset_name)
        images: tuple[bytes, ...] = ()
        if self._blob_store is not None:
            try:
                resolved = await resolve_images(request, spec, self._blob_store)
                images = tuple(r.data for r in resolved)
            except ValueError as exc:
                self._record_failure(InferenceErrorCode.PRESET_NOT_CONFIGURED)
                return GenerationResult.failure(
                    InferenceError(InferenceErrorCode.PRESET_NOT_CONFIGURED, str(exc))
                )

        grammar_schema = resolve_schema(request)

        try:
            worker = await self.get_worker(request.preset)
        except ModelLoadFailed as exc:
            self._record_failure(InferenceErrorCode.MODEL_LOAD_FAILED)
            return GenerationResult.failure(
                InferenceError(InferenceErrorCode.MODEL_LOAD_FAILED, str(exc))
            )

        def _record_retry() -> None:
            if self._metrics is not None:
                self._metrics.increment("truncation_retry_count")

        try:
            result = await worker.submit(request, grammar_schema, images, on_retry=_record_retry)
        except GenerationTimeout as exc:
            self._record_failure(InferenceErrorCode.GENERATION_TIMEOUT)
            duration_ms = int((time.monotonic() - start) * 1000)
            return GenerationResult.failure(
                InferenceError(InferenceErrorCode.GENERATION_TIMEOUT, str(exc)), duration_ms
            )
        except WorkerUnavailable as exc:
            self._record_failure(InferenceErrorCode.WORKER_UNAVAILABLE)
            duration_ms = int((time.monotonic() - start) * 1000)
            return GenerationResult.failure(
                InferenceError(InferenceErrorCode.WORKER_UNAVAILABLE, str(exc)), duration_ms
            )
        except GenerationCrashed as exc:
            self._record_failure(InferenceErrorCode.GENERATION_CRASHED)
            duration_ms = int((time.monotonic() - start) * 1000)
            return GenerationResult.failure(
                InferenceError(InferenceErrorCode.GENERATION_CRASHED, str(exc)), duration_ms
            )

        if self._metrics is not None:
            if result.error is not None:
                self._record_failure(result.error.code)
            else:
                self._metrics.increment("generations_succeeded")
                if not result.schema_valid:
                    self._metrics.increment("schema_violation_count")
        return result

    def _record_failure(self, code: InferenceErrorCode) -> None:
        if self._metrics is None:
            return
        self._metrics.increment("generations_failed")
        counter_by_code = {
            InferenceErrorCode.GENERATION_TIMEOUT: "generation_timeout_count",
            InferenceErrorCode.GENERATION_CRASHED: "generation_crashed_count",
            InferenceErrorCode.MODEL_LOAD_FAILED: "model_load_failed_count",
        }
        counter = counter_by_code.get(code)
        if counter is not None:
            self._metrics.increment(counter)

    async def shutdown(self) -> None:
        for worker in self._loaded_workers.values():
            await worker.shutdown()
        self._loaded_workers.clear()
        for reservation_id in self._reservations.values():
            await self._health_client.release(reservation_id)
        self._reservations.clear()

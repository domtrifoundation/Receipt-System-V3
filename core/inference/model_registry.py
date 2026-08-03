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
import os
import time
from dataclasses import dataclass, field

from common.frozen_dict import FrozenDict

from .contracts import (
    GenerationRequest,
    GenerationResult,
    InferenceError,
    InferenceErrorCode,
)
from .errors import GenerationCrashed, GenerationTimeout, ModelLoadFailed, WorkerUnavailable
from .generation import PresetWorker, TruncationConfig
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
    default_preset: str = "phi4-mini"
    vision_preset: str = "phi4-vision"
    device_by_preset: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    models_dir: str = "models"
    batch_window_ms: int = 30
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
    ) -> None:
        self._config = config or InferenceConfig()
        self._blob_store = blob_store
        self._metrics = metrics
        #: Defaults to real `PresetWorker` construction. Overridable so
        #: `tests/unit/core/inference/test_model_registry.py` can inject a fake-backed
        #: worker to exercise the real §6.2 lazy-load-locking race without real model
        #: weights — same seam shape as `generation.py`'s own `backend_factory`.
        self._worker_factory = worker_factory or self._default_worker
        self._loaded_workers: dict[str, PresetWorker] = {}
        self._load_locks: dict[str, asyncio.Lock] = collections.defaultdict(asyncio.Lock)

    def _default_worker(self, preset_name: str) -> PresetWorker:
        return PresetWorker(
            preset_name,
            self._model_dir_for(preset_name),
            self._device_for(preset_name),
            batch_window_ms=self._config.batch_window_ms,
            truncation=TruncationConfig(retry_multiplier=self._config.truncation_retry_multiplier),
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
            worker = self._worker_factory(preset_name)
            await worker.load()
            self._loaded_workers[preset_name] = worker
            return worker

    def available_presets(self) -> frozenset[str]:
        return frozenset(MODEL_PRESETS)

    def enabled_presets(self) -> frozenset[str]:
        return self.available_presets() & self._config.presets_enabled

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        start = time.monotonic()
        if request.preset not in self.enabled_presets():
            self._record_failure(InferenceErrorCode.PRESET_NOT_CONFIGURED)
            return GenerationResult.failure(
                InferenceError(
                    InferenceErrorCode.PRESET_NOT_CONFIGURED,
                    f"preset {request.preset!r} is not configured/enabled",
                )
            )

        spec = PresetSpec(request.preset)
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

        try:
            result = await worker.submit(request, grammar_schema, images)
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

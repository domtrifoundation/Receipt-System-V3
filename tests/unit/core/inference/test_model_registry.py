"""`InferenceModelRegistry` (deep-dive §6.2, §11) — the lazy-load-locking race is this
package's own named required regression test: two concurrent `get_worker()` calls for an
unloaded preset must result in exactly one `load()` call, never two racing loads.

Uses a fake, in-process worker (not real multiprocessing) for the locking test itself —
the race being tested is `asyncio.Lock` behaviour in the parent process, independent of
whatever `PresetWorker.load()` actually does underneath; `test_generation.py` already
covers the real multiprocessing mechanics separately.
"""

from __future__ import annotations

import asyncio

import pytest

from core.inference.contracts import GenerationRequest, MessageRole
from core.inference.model_registry import InferenceConfig, InferenceModelRegistry

from .conftest import run, text_message


class _FakeWorker:
    load_call_count = 0  # class-level, shared across every instance a factory makes

    def __init__(self, preset_name: str) -> None:
        self.preset_name = preset_name
        self._loaded = False

    async def load(self) -> None:
        await asyncio.sleep(0.05)  # simulate real model-load latency, widening the race window
        type(self).load_call_count += 1
        self._loaded = True

    def is_alive(self) -> bool:
        return self._loaded

    async def submit(self, request, grammar_schema, images=()):
        from core.inference.contracts import FinishReason, GenerationResult

        return GenerationResult(
            text="fake", tool_call=None, finish_reason=FinishReason.STOP,
            schema_valid=True, device="cpu", duration_ms=1,
        )

    async def shutdown(self) -> None:
        self._loaded = False


def _request() -> GenerationRequest:
    return GenerationRequest(
        run_id="r1", user_id="u1", preset="phi4-mini",
        messages=(text_message(MessageRole.USER, "hi"),),
    )


def test_concurrent_get_worker_calls_result_in_exactly_one_load():
    _FakeWorker.load_call_count = 0
    registry = InferenceModelRegistry(worker_factory=lambda name: _FakeWorker(name))

    async def go():
        workers = await asyncio.gather(*(registry.get_worker("phi4-mini") for _ in range(10)))
        return workers

    workers = run(go())
    assert _FakeWorker.load_call_count == 1
    assert all(w is workers[0] for w in workers)


def test_different_presets_load_independently_without_serializing():
    calls = []

    class _TrackingWorker(_FakeWorker):
        async def load(self) -> None:
            calls.append(self.preset_name)
            await super().load()

    registry = InferenceModelRegistry(worker_factory=lambda name: _TrackingWorker(name))

    async def go():
        await asyncio.gather(
            registry.get_worker("phi4-mini"), registry.get_worker("phi4-vision")
        )

    run(go())
    assert set(calls) == {"phi4-mini", "phi4-vision"}


def test_generate_fails_fast_for_an_unconfigured_preset():
    registry = InferenceModelRegistry(InferenceConfig(presets_enabled=frozenset()))
    request = _request()
    result = run(registry.generate(request))
    assert result.error is not None
    assert result.error.code.value == "preset_not_configured"


def test_generate_succeeds_through_a_fake_worker_end_to_end():
    registry = InferenceModelRegistry(
        InferenceConfig(presets_enabled=frozenset({"phi4-mini"})),
        worker_factory=lambda name: _FakeWorker(name),
    )
    result = run(registry.generate(_request()))
    assert result.error is None
    assert result.text == "fake"

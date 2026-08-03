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


class _FakeHealthClient:
    """Real async shape, fake outcome — the real `_default_worker` device-resolution
    logic (deep-dive §8.6) is what's under test here, not `HealthClient`'s own gRPC
    plumbing (`test_health_client.py` covers that against a real Health service)."""

    def __init__(self, granted: bool) -> None:
        self.granted = granted
        self.reserved_devices: list[str] = []
        self.released: list[str] = []

    async def reserve(self, owning_api, device_id, mb):
        from core.inference.health_client import ReservationResult

        self.reserved_devices.append(device_id)
        return ReservationResult(granted=self.granted, reservation_id="res-1" if self.granted else "")

    async def release(self, reservation_id, reason="released"):
        self.released.append(reservation_id)
        return True


def test_default_worker_never_calls_health_for_a_cpu_configured_preset(monkeypatch):
    import core.inference.model_registry as mr_module

    monkeypatch.setattr(mr_module, "PresetWorker", lambda *a, **kw: _FakeWorker(a[0]))
    fake_health = _FakeHealthClient(granted=True)
    registry = InferenceModelRegistry(
        InferenceConfig(presets_enabled=frozenset({"phi4-mini"})), health_client=fake_health,
    )
    run(registry.get_worker("phi4-mini"))
    assert fake_health.reserved_devices == []


def test_default_worker_falls_back_to_cpu_when_health_rejects(monkeypatch):
    import core.inference.model_registry as mr_module
    from common.frozen_dict import FrozenDict

    captured_device = {}

    def fake_preset_worker(preset_name, model_dir, device, **kwargs):
        captured_device["device"] = device
        return _FakeWorker(preset_name)

    monkeypatch.setattr(mr_module, "PresetWorker", fake_preset_worker)
    fake_health = _FakeHealthClient(granted=False)
    config = InferenceConfig(
        presets_enabled=frozenset({"phi4-mini"}),
        device_by_preset=FrozenDict({"phi4-mini": "cuda"}),
    )
    registry = InferenceModelRegistry(config, health_client=fake_health)
    run(registry.get_worker("phi4-mini"))

    assert fake_health.reserved_devices == ["cuda"]
    assert captured_device["device"] == "cpu"
    assert registry._reservations == {}


def test_default_worker_stays_on_gpu_when_health_grants(monkeypatch):
    import core.inference.model_registry as mr_module
    from common.frozen_dict import FrozenDict

    captured_device = {}

    def fake_preset_worker(preset_name, model_dir, device, **kwargs):
        captured_device["device"] = device
        return _FakeWorker(preset_name)

    monkeypatch.setattr(mr_module, "PresetWorker", fake_preset_worker)
    fake_health = _FakeHealthClient(granted=True)
    config = InferenceConfig(
        presets_enabled=frozenset({"phi4-mini"}),
        device_by_preset=FrozenDict({"phi4-mini": "cuda"}),
    )
    registry = InferenceModelRegistry(config, health_client=fake_health)
    run(registry.get_worker("phi4-mini"))

    assert captured_device["device"] == "cuda"
    assert registry._reservations == {"phi4-mini": "res-1"}


def test_shutdown_releases_every_tracked_reservation(monkeypatch):
    import core.inference.model_registry as mr_module
    from common.frozen_dict import FrozenDict

    monkeypatch.setattr(
        mr_module, "PresetWorker", lambda preset_name, model_dir, device, **kw: _FakeWorker(preset_name)
    )
    fake_health = _FakeHealthClient(granted=True)
    config = InferenceConfig(
        presets_enabled=frozenset({"phi4-mini"}),
        device_by_preset=FrozenDict({"phi4-mini": "cuda"}),
    )
    registry = InferenceModelRegistry(config, health_client=fake_health)
    run(registry.get_worker("phi4-mini"))
    run(registry.shutdown())

    assert fake_health.released == ["res-1"]
    assert registry._reservations == {}

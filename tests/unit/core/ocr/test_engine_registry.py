"""`OcrEngineRegistry` (deep-dive §6) — dispatch, availability, cloud budget enforcement,
timeout, and exception-to-wire-error conversion, all against fake `OcrEngine` stand-ins
rather than real (heavy, slow, sometimes paid) engine adapters. The real adapters get their
own live-hardware tests elsewhere in this package; this module's job is to prove the
registry's own orchestration logic is correct in isolation.
"""

from __future__ import annotations

import asyncio

import pytest

from core.ocr.contracts import (
    BlobRef,
    EngineName,
    EngineReading,
    OcrErrorCode,
    OcrRequest,
)
from core.ocr.engine_registry import OcrConfig, OcrEngineRegistry
from core.ocr.engines.cloud_engines.base_cloud_engine import CloudEngineConfig
from core.ocr.errors import OcrEngineCrashed, OcrEngineUnavailable

from .conftest import FakeBlobStore, run


class _FakeEngine:
    def __init__(self, name: EngineName, *, available: bool = True, behavior=None) -> None:
        self._name = name
        self._available = available
        self._behavior = behavior or (lambda image_bytes: EngineReading(
            engine=name, text="fake text", duration_ms=1
        ))

    @property
    def engine(self) -> EngineName:
        return self._name

    async def is_available(self) -> bool:
        return self._available

    async def read(self, image_bytes: bytes) -> EngineReading:
        result = self._behavior(image_bytes)
        if isinstance(result, Exception):
            raise result
        return result


def _registry_with_fakes(fakes: dict[EngineName, _FakeEngine], blob_store, config=None) -> OcrEngineRegistry:
    registry = OcrEngineRegistry(config or OcrConfig(), blob_store)
    registry._engines.update(fakes)  # test-only: swap in fakes after construction
    return registry


def test_available_engines_reflects_live_probes(blob_store):
    fakes = {
        EngineName.TESSERACT: _FakeEngine(EngineName.TESSERACT, available=True),
        EngineName.RAPIDOCR: _FakeEngine(EngineName.RAPIDOCR, available=False),
    }
    registry = _registry_with_fakes(fakes, blob_store)

    async def go():
        available = await registry.available_engines()
        return available

    available = run(go())
    assert EngineName.TESSERACT in available
    assert EngineName.RAPIDOCR not in available


def test_enabled_engines_is_available_intersect_config(blob_store):
    fakes = {
        EngineName.TESSERACT: _FakeEngine(EngineName.TESSERACT, available=True),
        EngineName.RAPIDOCR: _FakeEngine(EngineName.RAPIDOCR, available=True),
    }
    config = OcrConfig(engines_enabled=frozenset({EngineName.TESSERACT}))
    registry = _registry_with_fakes(fakes, blob_store, config)

    enabled = run(registry.enabled_engines())
    assert enabled == {EngineName.TESSERACT}


def test_run_returns_one_reading_per_requested_engine_even_on_crash(blob_store):
    blob_store.blobs["img1"] = b"fake-bytes"
    fakes = {
        EngineName.TESSERACT: _FakeEngine(EngineName.TESSERACT),
        EngineName.RAPIDOCR: _FakeEngine(
            EngineName.RAPIDOCR, behavior=lambda b: OcrEngineCrashed("native crash")
        ),
    }
    registry = _registry_with_fakes(fakes, blob_store)

    request = OcrRequest(
        run_id="r1", user_id="u1", image_ref=BlobRef(logical_id="img1"),
        engines=frozenset({EngineName.TESSERACT, EngineName.RAPIDOCR}),
    )
    result = run(registry.run(request))

    assert len(result.readings) == 2
    by_engine = {r.engine: r for r in result.readings}
    assert by_engine[EngineName.TESSERACT].error is None
    assert by_engine[EngineName.RAPIDOCR].error.code == OcrErrorCode.ENGINE_CRASHED


def test_run_maps_unavailable_exception_to_wire_code(blob_store):
    blob_store.blobs["img1"] = b"fake-bytes"
    fakes = {
        EngineName.TESSERACT: _FakeEngine(
            EngineName.TESSERACT, behavior=lambda b: OcrEngineUnavailable("no binary")
        ),
    }
    registry = _registry_with_fakes(fakes, blob_store)
    request = OcrRequest(
        run_id="r1", user_id="u1", image_ref=BlobRef(logical_id="img1"),
        engines=frozenset({EngineName.TESSERACT}),
    )
    result = run(registry.run(request))
    assert result.readings[0].error.code == OcrErrorCode.ENGINE_UNAVAILABLE


def test_run_maps_unexpected_bare_exception_to_engine_crashed(blob_store):
    """An adapter raising something outside this package's own taxonomy entirely — a raw
    RapidOCR/PaddleOCR native exception, say — still becomes a crash, never propagates
    through the registry (`engine_registry.py`'s own module docstring)."""
    blob_store.blobs["img1"] = b"fake-bytes"
    fakes = {
        EngineName.TESSERACT: _FakeEngine(
            EngineName.TESSERACT, behavior=lambda b: RuntimeError("totally unanticipated")
        ),
    }
    registry = _registry_with_fakes(fakes, blob_store)
    request = OcrRequest(
        run_id="r1", user_id="u1", image_ref=BlobRef(logical_id="img1"),
        engines=frozenset({EngineName.TESSERACT}),
    )
    result = run(registry.run(request))
    assert result.readings[0].error.code == OcrErrorCode.ENGINE_CRASHED


def test_run_times_out_a_slow_engine(blob_store):
    blob_store.blobs["img1"] = b"fake-bytes"

    class _SlowEngine(_FakeEngine):
        async def read(self, image_bytes: bytes) -> EngineReading:
            await asyncio.sleep(1.0)
            return EngineReading(engine=self._name, text="too slow", duration_ms=1000)

    fakes = {EngineName.TESSERACT: _SlowEngine(EngineName.TESSERACT)}
    registry = _registry_with_fakes(fakes, blob_store)
    request = OcrRequest(
        run_id="r1", user_id="u1", image_ref=BlobRef(logical_id="img1"),
        engines=frozenset({EngineName.TESSERACT}), timeout_ms=50,
    )
    result = run(registry.run(request))
    assert result.readings[0].error.code == OcrErrorCode.ENGINE_TIMEOUT


def test_cloud_budget_is_enforced_before_the_call_and_resets_per_run(blob_store):
    blob_store.blobs["img1"] = b"fake-bytes"
    call_count = {"n": 0}

    def _behavior(image_bytes):
        call_count["n"] += 1
        return EngineReading(engine=EngineName.CLOUD_VISION, text="cloud text", duration_ms=1)

    fakes = {EngineName.CLOUD_VISION: _FakeEngine(EngineName.CLOUD_VISION, behavior=_behavior)}
    config = OcrConfig(cloud_vision=CloudEngineConfig(api_key="k", max_calls_per_run=1))
    registry = _registry_with_fakes(fakes, blob_store, config)

    request = OcrRequest(
        run_id="run-a", user_id="u1", image_ref=BlobRef(logical_id="img1"),
        engines=frozenset({EngineName.CLOUD_VISION}),
    )
    first = run(registry.run(request))
    second = run(registry.run(request))  # same run_id — budget already spent

    assert first.readings[0].error is None
    assert second.readings[0].error.code == OcrErrorCode.BUDGET_EXCEEDED
    assert call_count["n"] == 1

    other_run_request = OcrRequest(
        run_id="run-b", user_id="u1", image_ref=BlobRef(logical_id="img1"),
        engines=frozenset({EngineName.CLOUD_VISION}),
    )
    third = run(registry.run(other_run_request))  # different run_id — fresh budget
    assert third.readings[0].error is None
    assert call_count["n"] == 2


def test_run_fails_every_requested_engine_when_blob_is_missing(blob_store):
    request = OcrRequest(
        run_id="r1", user_id="u1", image_ref=BlobRef(logical_id="does-not-exist"),
        engines=frozenset({EngineName.TESSERACT, EngineName.RAPIDOCR}),
    )
    registry = OcrEngineRegistry(OcrConfig(), blob_store)
    result = run(registry.run(request))
    assert len(result.readings) == 2
    assert all(r.error.code == OcrErrorCode.BLOB_NOT_FOUND for r in result.readings)

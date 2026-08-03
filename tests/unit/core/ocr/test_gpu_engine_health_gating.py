"""RapidOCR's/PaddleOCR's own Health-API-gated GPU device resolution (deep-dive §5.6) —
confirms the real behavior manually verified during development: a `"cpu"`-configured
engine never even calls Health, and a `"cuda"`-configured engine falls back to CPU when
Health rejects the reservation (the actual current state, since Setup API doesn't publish
a `HardwareProfile` yet) or stays on GPU when a real profile grants one.
"""

from __future__ import annotations

import asyncio

import pytest

from core.ocr.engines.rapidocr_engine import RapidOcrConfig, RapidOcrEngine
from core.ocr.engines.paddleocr_engine import PaddleOcrConfig, PaddleOcrEngine
from core.ocr.health_client import HealthClient, ReservationResult


class _FakeHealthClient:
    def __init__(self, granted: bool) -> None:
        self.granted = granted
        self.reserve_calls = 0

    async def reserve(self, owning_api, device_id, mb):
        self.reserve_calls += 1
        return ReservationResult(granted=self.granted, reservation_id="r1" if self.granted else "")

    async def release(self, reservation_id, reason="released"):
        return True


def test_rapidocr_cpu_config_never_calls_health():
    fake_health = _FakeHealthClient(granted=True)
    engine = RapidOcrEngine(RapidOcrConfig(device="cpu"), fake_health)
    use_cuda = asyncio.run(engine._resolve_use_cuda())
    assert use_cuda is False
    assert fake_health.reserve_calls == 0


def test_rapidocr_cuda_config_falls_back_to_cpu_on_rejection():
    fake_health = _FakeHealthClient(granted=False)
    engine = RapidOcrEngine(RapidOcrConfig(device="cuda"), fake_health)
    use_cuda = asyncio.run(engine._resolve_use_cuda())
    assert use_cuda is False
    assert fake_health.reserve_calls == 1


def test_rapidocr_cuda_config_stays_on_gpu_when_granted():
    fake_health = _FakeHealthClient(granted=True)
    engine = RapidOcrEngine(RapidOcrConfig(device="cuda"), fake_health)
    use_cuda = asyncio.run(engine._resolve_use_cuda())
    assert use_cuda is True


def test_rapidocr_resolution_is_cached_not_re_reserved_per_call():
    fake_health = _FakeHealthClient(granted=True)
    engine = RapidOcrEngine(RapidOcrConfig(device="cuda"), fake_health)
    asyncio.run(engine._resolve_use_cuda())
    asyncio.run(engine._resolve_use_cuda())
    assert fake_health.reserve_calls == 1


def test_paddleocr_cpu_config_never_calls_health():
    fake_health = _FakeHealthClient(granted=True)
    engine = PaddleOcrEngine(PaddleOcrConfig(device="cpu"), fake_health)
    use_gpu = asyncio.run(engine._resolve_use_gpu())
    assert use_gpu is False
    assert fake_health.reserve_calls == 0


def test_paddleocr_cuda_config_falls_back_to_cpu_on_rejection():
    fake_health = _FakeHealthClient(granted=False)
    engine = PaddleOcrEngine(PaddleOcrConfig(device="cuda"), fake_health)
    use_gpu = asyncio.run(engine._resolve_use_gpu())
    assert use_gpu is False


@pytest.mark.slow
def test_rapidocr_real_end_to_end_against_a_real_health_service():
    """The concrete, real end-to-end validation: a real Health service with no
    `HardwareProfile` published rejects the reservation, and the engine correctly runs on
    CPU regardless — not just a fake-health unit test of the same logic."""
    pytest.importorskip("rapidocr_onnxruntime", reason="rapidocr-onnxruntime has no prebuilt wheel for this interpreter yet")
    grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

    from core.health.service import serve as health_serve
    from .conftest import make_text_png

    server = health_serve("127.0.0.1:19763")
    try:
        health_client = HealthClient("127.0.0.1:19763")
        engine = RapidOcrEngine(RapidOcrConfig(device="cuda"), health_client)
        image = make_text_png("HELLO RECEIPT")
        reading = asyncio.run(engine.read(image))
        assert reading.error is None
        assert reading.device == "cpu"  # Health rejected the cuda reservation
    finally:
        server.stop(None)

"""`HealthClient` (deep-dive §8.6) — identical shape and identical real behavior to
`core/ocr/health_client.py`'s own tests, exercised against a real, in-process Health
service."""

from __future__ import annotations

import asyncio

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.health.service import serve as health_serve  # noqa: E402
from core.health.resource_ledger import StaticHardwareProfile  # noqa: E402
from core.inference.health_client import HealthClient  # noqa: E402


@pytest.mark.slow
def test_reserve_is_rejected_with_no_hardware_profile_published():
    server = health_serve("127.0.0.1:19764")
    try:
        client = HealthClient("127.0.0.1:19764")
        result = asyncio.run(client.reserve("inference", "gpu0", 3000))
        assert result.granted is False
        assert result.rejection_reason == "UNKNOWN_DEVICE"
    finally:
        server.stop(None)


@pytest.mark.slow
def test_reserve_is_granted_against_a_real_published_profile():
    profile = StaticHardwareProfile({"cuda": 8000})
    server = health_serve("127.0.0.1:19765", profile=profile)
    try:
        client = HealthClient("127.0.0.1:19765")
        result = asyncio.run(client.reserve("inference", "cuda", 3000))
        assert result.granted is True
        released = asyncio.run(client.release(result.reservation_id))
        assert released is True
    finally:
        server.stop(None)


@pytest.mark.slow
def test_reserve_against_an_unreachable_service_falls_back_gracefully():
    client = HealthClient("127.0.0.1:19768", timeout_seconds=1.0)
    result = asyncio.run(client.reserve("inference", "cuda", 3000))
    assert result.granted is False
    assert result.rejection_reason == "health_service_unreachable"

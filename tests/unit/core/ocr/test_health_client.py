"""`HealthClient` (deep-dive §5.6) — real gRPC calls against a real, in-process Health
service, not mocked. Confirms both real outcomes: a real service with no `HardwareProfile`
published rejects every reservation (the actual current state, since Setup API doesn't
publish one yet), and an unreachable service degrades to the same "not granted" answer
rather than raising — a rejected/unreachable GPU reservation is a performance
degradation, never treated as fail-closed the way Content Security's own client is.
"""

from __future__ import annotations

import asyncio

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.health.service import serve as health_serve  # noqa: E402
from core.health.resource_ledger import StaticHardwareProfile  # noqa: E402
from core.ocr.health_client import HealthClient  # noqa: E402


@pytest.mark.slow
def test_reserve_is_rejected_with_no_hardware_profile_published():
    server = health_serve("127.0.0.1:19760")
    try:
        client = HealthClient("127.0.0.1:19760")
        result = asyncio.run(client.reserve("ocr", "gpu0", 512))
        assert result.granted is False
        assert result.rejection_reason == "UNKNOWN_DEVICE"
    finally:
        server.stop(None)


@pytest.mark.slow
def test_reserve_is_granted_against_a_real_published_profile():
    profile = StaticHardwareProfile({"gpu0": 8000})
    server = health_serve("127.0.0.1:19761", profile=profile)
    try:
        client = HealthClient("127.0.0.1:19761")
        result = asyncio.run(client.reserve("ocr", "gpu0", 512))
        assert result.granted is True
        assert result.reservation_id

        released = asyncio.run(client.release(result.reservation_id))
        assert released is True
    finally:
        server.stop(None)


@pytest.mark.slow
def test_reserve_against_an_unreachable_service_falls_back_gracefully():
    client = HealthClient("127.0.0.1:19769", timeout_seconds=1.0)  # nothing listening
    result = asyncio.run(client.reserve("ocr", "gpu0", 512))
    assert result.granted is False
    assert result.rejection_reason == "health_service_unreachable"


@pytest.mark.slow
def test_release_of_an_unknown_reservation_is_false_not_an_exception():
    server = health_serve("127.0.0.1:19762")
    try:
        client = HealthClient("127.0.0.1:19762")
        released = asyncio.run(client.release("this-reservation-id-does-not-exist"))
        assert released is False
    finally:
        server.stop(None)

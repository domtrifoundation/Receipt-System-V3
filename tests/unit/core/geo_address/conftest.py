"""Shared fixtures for Geo/Address's unit tests.

**No test in this package touches the network.** `FakeProvider` implements the `GeoProvider`
Protocol directly for corroboration-layer tests; `FakeTransport` implements `GeoHttpTransport`
for the three real provider adapters' own response-parsing tests. Both are hand-written fakes
injected at the registry boundary, never a mock of a real HTTP client.

**Every clock this suite needs is injected.** `GeoCache`'s staleness window is purely about the
passage of time (§4) — a test that reached for a real 90-day-old file would not exist. `clock`
below is the same hand-advanced-UTC-clock shape Health's own `conftest.py` uses for its TTL
tests, applied here to cache staleness instead of reservation expiry.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from core.geo_address.contracts import GeoAddress, ProviderCandidateResult
from core.geo_address.errors import ProviderRequestFailed


def run(coro):
    """Drive one coroutine to completion. Each call gets its own loop, deliberately — a
    leaked loop between tests would make an ordering bug look like a flake (the same reasoning
    Audit's own `conftest.py` states for not reaching for `pytest-asyncio`)."""
    return asyncio.run(coro)


class FakeClock:
    """A hand-advanced UTC clock, passed as `GeoCache`'s `now=` callable."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_address(formatted: str, *, city: str = "Manila", lat: float = 14.5995, lon: float = 120.9842, **kwargs) -> GeoAddress:
    return GeoAddress(formatted=formatted, city=city, latitude=lat, longitude=lon, **kwargs)


class FakeProvider:
    """A `GeoProvider` Protocol implementation entirely in memory — no transport, no network.

    `answers` maps a candidate string to the `GeoAddress` this provider returns for it;
    `fail_on` names candidate strings this provider raises `ProviderRequestFailed` for instead
    (the single-provider-down-for-this-call case, distinct from `available=False`, which is
    the never-configured case `corroboration.py` skips before making any call at all).
    """

    def __init__(
        self,
        name: str,
        *,
        available: bool = True,
        answers: dict[str, GeoAddress] | None = None,
        fail_on: frozenset[str] = frozenset(),
        confidence: float | dict[str, float] = 0.8,
        delay: float = 0.0,
        reverse_name: str | None = None,
        reverse_fails: bool = False,
    ) -> None:
        self._name = name
        self._available = available
        self._answers = answers or {}
        self._fail_on = fail_on
        self._confidence = confidence
        self._delay = delay
        self._reverse_name = reverse_name
        self._reverse_fails = reverse_fails
        self.geocode_calls: list[str] = []
        self.reverse_calls: list[tuple[float, float]] = []

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return self._available

    async def geocode(self, candidate_string: str, *, country_code: str) -> ProviderCandidateResult:
        self.geocode_calls.append(candidate_string)
        if self._delay:
            await asyncio.sleep(self._delay)
        if candidate_string in self._fail_on:
            raise ProviderRequestFailed(f"{self._name} failed on {candidate_string!r}")
        address = self._answers.get(candidate_string)
        if address is None:
            raise ProviderRequestFailed(f"{self._name} has no answer for {candidate_string!r}")
        confidence = (
            self._confidence.get(candidate_string, 0.5)
            if isinstance(self._confidence, dict)
            else self._confidence
        )
        return ProviderCandidateResult(
            provider=self._name, candidate_string=candidate_string, address=address, confidence=confidence
        )

    async def reverse(self, latitude: float, longitude: float, *, country_code: str) -> ProviderCandidateResult:
        self.reverse_calls.append((latitude, longitude))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._reverse_fails or self._reverse_name is None:
            raise ProviderRequestFailed(f"{self._name} has no reverse answer here")
        return ProviderCandidateResult(
            provider=self._name,
            candidate_string="",
            address=make_address(f"reverse:{self._name}"),
            confidence=0.6,
            matched_business_name=self._reverse_name,
        )


class FakeTransport:
    """A `GeoHttpTransport` Protocol implementation for the real provider adapters' own
    response-parsing tests. `responses` is either one canned payload for every call, or a
    callable `(url, params) -> payload` for a test that needs to vary the answer by request."""

    def __init__(self, responses) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def get_json(self, url: str, *, params):
        self.calls.append((url, dict(params)))
        if callable(self._responses):
            return self._responses(url, dict(params))
        return self._responses


__all__ = ["FakeClock", "FakeProvider", "FakeTransport", "make_address", "run"]

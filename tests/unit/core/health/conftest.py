"""Shared fixtures for Health API's unit tests.

**Every clock in this package is injected, and these fixtures are why.** The two guarantees
Health's deep-dive asks for tests of — §5.2's abandoned-reservation cleanup and §10's
hung-not-crashed detection — are both purely about the passage of time. A test that reached
for `time.sleep` to exercise them would take two minutes to run the default TTL once and would
still be testing the sleep rather than the expiry. `FakeClock` makes them deterministic and
instant, which is the difference between those tests existing and not.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.health.resource_ledger import ResourceLedger, StaticHardwareProfile


class FakeClock:
    """A hand-advanced UTC clock, passed as the `now=` callable everywhere."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now = self.now + timedelta(seconds=seconds)
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def profile() -> StaticHardwareProfile:
    """A two-device profile standing in for Setup API's published `HardwareProfile`.

    Real values rather than round numbers: 8188 MB is the sort of figure a real card reports
    once its own overhead is subtracted, and a test that only ever divides 8192 by 2 cleanly
    would not notice an off-by-one in the capacity comparison.
    """
    return StaticHardwareProfile({"gpu:0": 8188, "gpu:1": 4096})


@pytest.fixture
def ledger(profile: StaticHardwareProfile, clock: FakeClock) -> ResourceLedger:
    return ResourceLedger(profile=profile, ttl_seconds=120, now=clock)

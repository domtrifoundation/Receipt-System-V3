"""Shared fixtures for Background Workers' unit tests.

Everything this package does is a function of two things it cannot observe directly — the
clock, and whether the system is busy — so both are injected. A test that reached for real
time could not exercise an interval at all without sleeping through it, and §10's
five-consecutive-failure guard needs five dispatches in a row with nothing waiting in between.

The handlers here are real callables run through the scheduler's actual routing, not mocks.
The guarantees under test are about what happens when a job raises or hangs, and a mock that
returns whatever the test told it to would exercise none of that.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.background_workers.contracts import JobClass, JobRegistration
from core.background_workers.idle_detection import IdleDetector, StaticRunState
from core.background_workers.registry import JobRegistry


class FakeClock:
    """A hand-advanced UTC clock, passed as the scheduler's `now=` callable."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 8, 2, 9, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now = self.now + timedelta(seconds=seconds)
        return self.now


class RecordingHandler:
    """A real job handler that counts its own invocations, and fails when told to.

    `fail_times` failing runs followed by successes is the shape §10's guard needs: the guard
    is about *consecutive* failures, so a test proving a success resets the counter has to be
    able to script exactly that sequence.
    """

    def __init__(self, *, fail_times: int = 0, always_fail: bool = False) -> None:
        self.calls = 0
        self._fail_times = fail_times
        self._always_fail = always_fail

    def __call__(self) -> None:
        self.calls += 1
        if self._always_fail or self.calls <= self._fail_times:
            raise RuntimeError(f"job failed on call {self.calls}")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def registry() -> JobRegistry:
    return JobRegistry()


@pytest.fixture
def idle_everywhere() -> IdleDetector:
    """A system with no active runs anywhere — the quiet case."""
    return IdleDetector(StaticRunState({}))


def registration(
    job_id: str = "log_retention_purge",
    *,
    owning_api: str = "logs",
    job_class: JobClass = JobClass.ASYNC_IO,
    idle_only: bool = False,
    interval_seconds: int | None = 60,
    scope: str = "global",
) -> JobRegistration:
    return JobRegistration(
        job_id=job_id,
        owning_api=owning_api,
        job_class=job_class,
        idle_only=idle_only,
        interval_seconds=interval_seconds,
        scope=scope,
    )

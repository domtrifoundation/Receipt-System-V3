"""Shared fixtures for Task Scheduler's unit tests.

Everything here is time-shaped, so the clock is a value passed in rather than a global to
patch. That is what makes §9's sleep/wake and §10's missed-run cases testable at all: both are
about what happens across an interval nobody sat through, and a test that reached for
`time.sleep` would be testing the sleep.

`run()` uses `asyncio.run` rather than `pytest-asyncio`, matching `core/audit`'s own conftest
— this repo deliberately does not carry that dependency, and adding one to the test tree for
what the stdlib already does would put a package in `requirements.txt` and in `noxfile.py`'s
narrow `FORWARD_COMPAT_DEPS` list for no behavioural gain.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from common.frozen_dict import FrozenDict
from core.task_scheduler.contracts import SchedulableAction, UserScheduledTask
from core.task_scheduler.registry import SchedulableActionRegistry

#: A Sunday, so the deep-dive's own example ("run a full rescan every Sunday at 2am") can be
#: tested against the literal expression §1 names rather than a contrived one.
SUNDAY_0100 = datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)
WEEKLY_SUNDAY_2AM = "0 2 * * 0"


def run(coro):
    return asyncio.run(coro)


def task(
    *,
    task_id: str = "task-1",
    created_by: str = "user-1",
    action: str = "full_rescan",
    cron_expression: str = WEEKLY_SUNDAY_2AM,
    enabled: bool = True,
    params: dict | None = None,
    created_at: datetime = SUNDAY_0100,
) -> UserScheduledTask:
    return UserScheduledTask(
        task_id=task_id,
        created_by=created_by,
        action=action,
        action_params=FrozenDict(params or {}),
        cron_expression=cron_expression,
        enabled=enabled,
        created_at=created_at,
        updated_at=created_at,
    )


class RecordingTrigger:
    """A real `ScheduleTrigger` implementation that records what it was asked to do.

    Not a mock: the point of §5's Provider Registry is that the dispatching service does not
    care which trigger is installed, so the tests drive the same interface a real
    `SupervisorWakeTrigger` implements rather than asserting against a stubbed call log.
    """

    def __init__(self, *, available: bool = True) -> None:
        self.registered: list[str] = []
        self.deregistered: list[str] = []
        self._available = available

    @property
    def name(self) -> str:
        return "recording"

    def is_available(self) -> bool:
        return self._available

    async def register_trigger(self, scheduled_task: UserScheduledTask) -> None:
        if not self._available:
            raise RuntimeError("trigger backend unavailable")
        self.registered.append(scheduled_task.task_id)

    async def deregister_trigger(self, task_id: str) -> None:
        self.deregistered.append(task_id)


@pytest.fixture
def registry() -> SchedulableActionRegistry:
    registry = SchedulableActionRegistry()
    registry.register(
        SchedulableAction(
            name="full_rescan",
            description="Re-run the pipeline over every stored receipt",
            param_keys=("since",),
        )
    )
    registry.register(
        SchedulableAction(
            name="generate_slsp_export",
            description="Generate the quarterly SLSP export",
            param_keys=("quarter",),
        )
    )
    return registry

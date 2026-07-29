"""`InAppTimerTrigger` — the simplest `ScheduleTrigger`, correct only under a real precondition
(`v3-deepdive-39-task-scheduler.md` §5).

**"Correct only when the dispatching service is guaranteed awake (`SleepPolicy.NEVER`) or
sleep/wake is disabled entirely."** This provider is a plain in-process check loop: it holds
no wake mechanism of its own beyond "something calls `check_due()` again later." If the
hosting process can sleep, nothing here notices a task came due while it was asleep — that is
exactly the bug `SupervisorWakeTrigger` exists to fix, and this class is deliberately *not*
the default for that reason, simplest or not.

**Firing and misfire semantics are not reimplemented here.** `firing.evaluate()` is the one
function every trigger defers to for "is this due, and what should the next check compare
against" (§10) — this class's own job is purely bookkeeping (which tasks are registered, what
each one's own checkpoint is) plus calling that function and the injected dispatch callback.
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
from datetime import datetime

from ..contracts import UserScheduledTask, utcnow
from ..firing import evaluate

#: The seam onto dispatch (`docs/PRINCIPLES.md` §1.3): once a task is due, *what actually
#: runs* is Background Workers' own classification/routing (deep-dive §1, §5) — this package
#: never reimplements that, so the callback is injected rather than this trigger importing a
#: dispatch module that does not belong to it.
DueCallback = Callable[[UserScheduledTask], Awaitable[None]]


class InAppTimerTrigger:
    """Registered tasks are held in memory only. A process restart loses every checkpoint —
    acceptable for this provider specifically, since it is only ever correct for a process
    that does not sleep in the first place, and starting fresh from each task's own
    `created_at` after a restart costs at most one recomputed "not yet due" check, never a
    duplicate fire."""

    def __init__(self, on_due: DueCallback, *, now: Callable[[], datetime] = utcnow) -> None:
        self._on_due = on_due
        self._now = now
        self._tasks: dict[str, UserScheduledTask] = {}
        self._checkpoints: dict[str, datetime] = {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "in_app_timer"

    def is_available(self) -> bool:
        """Always available — it is exactly as available as this process's own event loop,
        which is the property that makes it *unsafe* to assume as the only path rather than
        the property that makes it unreliable on its own terms."""
        return True

    async def register_trigger(self, task: UserScheduledTask) -> None:
        with self._lock:
            self._tasks[task.task_id] = task
            self._checkpoints.setdefault(task.task_id, task.created_at)

    async def deregister_trigger(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)
            self._checkpoints.pop(task_id, None)

    async def check_due(self, now: datetime | None = None) -> tuple[str, ...]:
        """Evaluate every registered, enabled task against `now` (defaulting to the injected
        clock) and dispatch every one that is due.

        Returns the `task_id`s that actually fired on this check — real, not a private
        implementation detail: it is what `tests/unit/core/task_scheduler` uses to assert
        against, and it is also what a real hosting loop would log. A task whose occurrence
        was missed (§10) advances its own checkpoint the identical way a fired one does, just
        without calling `on_due` — see `firing.evaluate`'s own docstring for why both branches
        update the checkpoint and "not yet due" does not.
        """
        moment = now if now is not None else self._now()
        with self._lock:
            items = list(self._tasks.items())
        fired: list[str] = []
        for task_id, task in items:
            if not task.enabled:
                continue
            with self._lock:
                last = self._checkpoints.get(task_id, task.created_at)
            decision = evaluate(task.cron_expression, last, moment)
            if decision.should_fire or decision.missed:
                with self._lock:
                    self._checkpoints[task_id] = decision.next_check_after
            if decision.should_fire:
                await self._on_due(task)
                fired.append(task_id)
        return tuple(fired)


__all__ = ["DueCallback", "InAppTimerTrigger"]

"""`TaskSchedulerService` — the real assembly point combining `TaskStore` (per-user
persistence), `SchedulableActionRegistry` (the allowlist), and `cron.parse`/
`enforce_task_cap` (creation-time validation) into the operations `grpc_servicer.py`'s
`TaskSchedulerServicer` exposes over the wire.

**This did not exist at all until this session** — `contracts.py`'s own docstring already
named the shape this file should take ("a caller resolving a session and finding it
insufficient for this call is `service.py`'s own concern, mirroring
`core/audit/service.py`'s injected, fail-closed `role_resolver`"), but nothing had built
it: no assembly layer, no `.proto`, no servicer. `CLAUDE.md`'s own "Known gap" section
named this by name.

Rejection happens at creation/update time, never at dispatch (§9's own testing hook) — an
unregistered `action` or a malformed `cron_expression` fails here, before a row is ever
written, exactly the same posture `store.py`'s own module docstring describes for the
in-process layer this wraps.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from common.frozen_dict import FrozenDict

from .contracts import (
    DeleteTaskResult,
    SchedulableActionsResult,
    TaskListResult,
    TaskResult,
    UserScheduledTask,
    utcnow,
)
from .cron import parse as parse_cron
from .errors import (
    InvalidTaskRequest,
    TaskNotFound,
    TaskSchedulerError,
    code_for,
)
from .registry import (
    DEFAULT_MAX_TASKS_PER_USER,
    SchedulableActionRegistry,
    default_registry,
    enforce_task_cap,
)
from .store import TaskStore

__all__ = ["TaskSchedulerService", "new_task_id"]


def new_task_id() -> str:
    """A UUID4 — a guessable id would make a user's own schedule trivially probeable,
    the same reasoning `core/audit/writer.py::new_event_id` and this session's other new
    id generators (`core/review_flagging/lifecycle.py::new_flag_id`) already give."""
    return f"task-{uuid4().hex[:12]}"


class TaskSchedulerService:
    """One process's whole surface: create, update, delete, list tasks; list the
    allowlist. Per-user isolation is `TaskStore`'s own structural guarantee (one database
    per user); this class adds nothing on top of that beyond the validation gates."""

    def __init__(
        self,
        *,
        store: TaskStore | None = None,
        actions: SchedulableActionRegistry | None = None,
        max_tasks_per_user: int | None = DEFAULT_MAX_TASKS_PER_USER,
        top_level: Path | str | None = None,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._store = store if store is not None else TaskStore(top_level)
        self._actions = actions if actions is not None else default_registry()
        self._max_tasks_per_user = max_tasks_per_user
        self._now = now

    @property
    def actions(self) -> SchedulableActionRegistry:
        return self._actions

    def _validate(self, action: str, action_params: object, cron_expression: str) -> None:
        """Raises on the first problem found — creation-time rejection, never a silent
        accept-and-fail-later at dispatch (§9's own testing hook)."""
        if not action or not cron_expression:
            raise InvalidTaskRequest("action and cron_expression are both required")
        if not isinstance(action_params, Mapping):
            raise InvalidTaskRequest("action_params must be a mapping")
        self._actions.require(action)
        parse_cron(cron_expression)

    async def create_task(
        self, user_id: str, action: str, action_params: Mapping, cron_expression: str,
        *, enabled: bool = True,
    ) -> TaskResult:
        try:
            self._validate(action, action_params, cron_expression)
            current_count = await self._store.count_for_user(user_id)
            enforce_task_cap(current_count, self._max_tasks_per_user)
        except TaskSchedulerError as exc:
            return TaskResult(ok=False, error_code=code_for(exc), error_detail=str(exc))

        now = self._now()
        task = UserScheduledTask(
            task_id=new_task_id(), created_by=user_id, action=action,
            action_params=FrozenDict(dict(action_params)), cron_expression=cron_expression,
            enabled=enabled, created_at=now, updated_at=now,
        )
        await self._store.insert(task)
        return TaskResult(ok=True, task=task)

    async def update_task(
        self, user_id: str, task_id: str, *,
        action: str | None = None, action_params: Mapping | None = None,
        cron_expression: str | None = None, enabled: bool | None = None,
    ) -> TaskResult:
        existing = await self._store.get(user_id, task_id)
        if existing is None:
            exc = TaskNotFound(task_id)
            return TaskResult(ok=False, error_code=code_for(exc), error_detail=str(exc))

        new_action = action if action is not None else existing.action
        new_params = action_params if action_params is not None else existing.action_params
        new_cron = cron_expression if cron_expression is not None else existing.cron_expression
        new_enabled = enabled if enabled is not None else existing.enabled

        try:
            self._validate(new_action, new_params, new_cron)
        except TaskSchedulerError as exc:
            return TaskResult(ok=False, error_code=code_for(exc), error_detail=str(exc))

        updated = replace(
            existing, action=new_action, action_params=FrozenDict(dict(new_params)),
            cron_expression=new_cron, enabled=new_enabled, updated_at=self._now(),
        )
        did_update = await self._store.update(updated)
        if not did_update:
            exc = TaskNotFound(task_id)
            return TaskResult(ok=False, error_code=code_for(exc), error_detail=str(exc))
        return TaskResult(ok=True, task=updated)

    async def delete_task(self, user_id: str, task_id: str) -> DeleteTaskResult:
        deleted = await self._store.delete(user_id, task_id)
        if not deleted:
            exc = TaskNotFound(task_id)
            return DeleteTaskResult(ok=False, error_code=code_for(exc), error_detail=str(exc))
        return DeleteTaskResult(ok=True)

    async def list_tasks(self, user_id: str) -> TaskListResult:
        tasks = await self._store.list_for_user(user_id)
        return TaskListResult(ok=True, tasks=tuple(tasks))

    def list_schedulable_actions(self) -> SchedulableActionsResult:
        return SchedulableActionsResult(ok=True, actions=self._actions.list())

    def close(self) -> None:
        self._store.close()

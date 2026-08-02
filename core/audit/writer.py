"""The append-only write path (`v3-deepdive-08-audit-event-log-api.md` §3.2).

**Read this before adding a method here.** There is no `update_event()` and no
`delete_event()` on this module's public surface, and adding one is not a change to be
weighed on its merits — the absence *is* the guarantee. A correction to a prior entry is a
new event carrying `corrects_event_id`, appended like any other. That is enforced three ways
that each work without the other two:

1. no such method exists here;
2. nothing here hands out the connection object a caller could route around it with;
3. the connection itself is opened under `db.py`'s `append` authorizer profile, so SQLite
   refuses an `UPDATE` or `DELETE` before executing it even if code inside this package
   tried (§3.2's own resolved mechanism, deep-dive open questions #2).

The reason for that much belt and braces is specific and worth restating rather than
assuming: this log's entire value is being trustworthy evidence in exactly the scenario
where someone would want to quietly alter it.

**Concurrency** (§6, `docs/PRINCIPLES.md` §5): local SQLite I/O, async-I/O bucket. The public
API is `async` and the blocking call is handed to a worker thread, so a slow disk never
stalls the event loop of the service hosting this. There is no compute-bound work here and
no free-threading relevance — privileged actions are rare by definition, so this path has no
hot-path concerns worth designing around.
"""

from __future__ import annotations

import asyncio
import collections.abc
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from common.frozen_dict import FrozenDict

from .contracts import (
    PRIVILEGED_ACTIONS,
    REASON_REQUIRED_ACTIONS,
    ActionType,
    AuditEvent,
    RecordResult,
)
from .db import utcnow
from .errors import (
    E_WRITE_FAILED,
    AuditError,
    InvalidEvent,
    ReasonRequired,
    UnknownPrivilegedAction,
)
from .sinks import SinkRegistry, SqliteAuditSink


def new_event_id() -> str:
    """A UUID4, not a sequence number. Two reasons, both real: the writer must be able to
    name an event before the database has accepted it (so a failed write still has a stable
    identity to report), and a guessable identifier would make it trivial to tell whether a
    given privileged action happened in a window without being able to read the log."""
    return f"aud_{uuid.uuid4().hex}"


def coerce_details(details: Any) -> FrozenDict:
    """Normalise a details payload to `FrozenDict`.

    The `isinstance` check is against `collections.abc.Mapping`, never `dict`. On Python
    3.15+ the builtin `frozendict` inherits directly from `object`, so an already-frozen
    payload would silently fail a `dict` check and get mis-handled — the exact gotcha
    `common/frozen_dict.py` documents (`docs/PRINCIPLES.md` §2.1).
    """
    if details is None:
        return FrozenDict({})
    if isinstance(details, collections.abc.Mapping):
        return FrozenDict(dict(details))
    raise InvalidEvent(f"details must be a Mapping, got {type(details).__name__}")


def validate(event: AuditEvent) -> None:
    """Raise if the event is not usable evidence. Internal — the writer turns this into
    result data before it reaches a boundary (`docs/PRINCIPLES.md` §4.1)."""
    if not isinstance(event.action_type, ActionType):
        raise InvalidEvent(f"action_type must be an ActionType, got {event.action_type!r}")
    if not event.event_id:
        raise InvalidEvent("event_id is required")
    if not event.actor_user_id:
        raise InvalidEvent("actor_user_id is required — an action with no actor is not evidence")
    if not isinstance(event.occurred_at, datetime):
        raise InvalidEvent("occurred_at must be a datetime")
    if not isinstance(event.details, collections.abc.Mapping):
        raise InvalidEvent("details must be a Mapping")
    if event.action_type in REASON_REQUIRED_ACTIONS and not (event.reason or "").strip():
        raise ReasonRequired(f"{event.action_type.value} requires a stated reason")


class AuditWriter:
    """The only way anything writes to the audit log.

    Construct with no arguments for the real top-level database, or pass a `db_path` in
    tests. Pass a real file, never `":memory:"` — this package opens separate connections
    under separate authorizer profiles, and two `":memory:"` connections are two unrelated
    databases, so an in-memory path silently gives the writer and the reader their own empty
    stores (see `tests/unit/core/audit/conftest.py`). Pass a pre-built `SinkRegistry` to add
    mirror sinks alongside the SQLite primary.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        registry: SinkRegistry | None = None,
    ) -> None:
        self._registry = registry or SinkRegistry(SqliteAuditSink(db_path))

    # ------------------------------------------------------------- write path
    async def record(self, event: AuditEvent) -> RecordResult:
        """Append one event. INSERT only.

        Never raises across the boundary: a validation failure, an unreachable primary sink
        and a degraded mirror are all reported through `RecordResult` (§4.1).
        """
        try:
            validate(event)
        except AuditError as exc:
            return RecordResult(
                recorded=False, event_id=event.event_id, error=exc.code, error_detail=str(exc)
            )

        try:
            degraded = await asyncio.to_thread(self._registry.fan_out, event)
        except AuditError as exc:
            return RecordResult(
                recorded=False, event_id=event.event_id, error=exc.code, error_detail=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - nothing unexpected escapes this boundary
            return RecordResult(
                recorded=False,
                event_id=event.event_id,
                error=E_WRITE_FAILED,
                error_detail=f"{type(exc).__name__}: {exc}",
            )

        return RecordResult(recorded=True, event_id=event.event_id, degraded_sinks=degraded)

    async def record_action(
        self,
        operation: str,
        actor_user_id: str,
        *,
        target_user_id: str | None = None,
        reason: str | None = None,
        details: Mapping | None = None,
        corrects_event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> RecordResult:
        """Record a privileged action by its canonical operation name.

        This is what every other API calls, and the reason it takes an operation name rather
        than an `ActionType` is the deep-dive's §7 coverage guarantee: the name must be
        present in `contracts.PRIVILEGED_ACTIONS`, so the set of privileged operations stays
        closed and a test can walk that table and confirm each one genuinely produces an
        entry — "a structural check against the list, not per-action trust."
        """
        action_type = PRIVILEGED_ACTIONS.get(operation)
        if action_type is None:
            exc = UnknownPrivilegedAction(
                f"{operation!r} is not a registered privileged action; add it to "
                f"contracts.PRIVILEGED_ACTIONS in the same change that introduces it"
            )
            return RecordResult(recorded=False, error=exc.code, error_detail=str(exc))

        try:
            payload = coerce_details(details)
        except AuditError as exc:
            return RecordResult(recorded=False, error=exc.code, error_detail=str(exc))

        return await self.record(
            AuditEvent(
                event_id=new_event_id(),
                action_type=action_type,
                actor_user_id=actor_user_id,
                occurred_at=occurred_at or utcnow(),
                target_user_id=target_user_id,
                reason=reason,
                details=payload,
                corrects_event_id=corrects_event_id,
            )
        )

    async def record_correction(
        self,
        corrects_event_id: str,
        operation: str,
        actor_user_id: str,
        *,
        reason: str,
        details: Mapping | None = None,
    ) -> RecordResult:
        """Correct a prior entry the only way this API allows: by appending a new one.

        Named explicitly rather than left as "call `record_action` with `corrects_event_id`"
        so that a future session looking for the edit path finds this and its docstring
        instead of concluding the edit path is missing by oversight.
        """
        return await self.record_action(
            operation,
            actor_user_id,
            reason=reason,
            details=details,
            corrects_event_id=corrects_event_id,
        )

    def close(self) -> None:
        self._registry.close()


__all__ = ["AuditWriter", "coerce_details", "new_event_id", "validate"]

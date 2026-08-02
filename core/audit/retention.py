"""Retention policy resolution and the one narrow deletion path in this package (§5).

**Why this is a separate module and not a method on `AuditWriter`.** Retention is the single
place where audit rows are legitimately removed, and putting a `DELETE` inside the
append-only writer would put it behind the same object every other API holds a handle to —
which is exactly the shape §3.2 rules out. Here it is isolated: its own module, its own
connection profile (`db.py`'s `purge`), and one method that takes no event id and no
predicate. The only thing a caller can express is "apply the configured policy."

**Retention default: 10 years.** BIR Revenue Regulations No. 17-2013, as amended by RR
5-2014, requires books of accounts and accounting records to be preserved for ten (10) years.
That is the researched source of `contracts.DEFAULT_RETENTION_DAYS`, and
`contracts.RETENTION_SETTING_SPEC` carries the citation into the settings surface itself so an
owner changing it is making an informed choice rather than adjusting an unexplained number.
Raising it, or switching to `indefinite`, is always permitted. Lowering it below the baseline
requires an explicit override with a stated reason — defaulting downward from a researched
legal baseline is exactly the quiet drift this project's hygiene discipline exists to prevent
(`docs/PRINCIPLES.md` §4.3).

**Purge records are themselves exempt from purging.** A `RETENTION_PURGE_EXECUTED` row is
never deleted by a later purge. Otherwise the trail of prunings would eventually prune
itself, and the one class of deletion this log permits would become the one it cannot
account for.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from common.frozen_dict import FrozenDict

from .contracts import (
    DEFAULT_RETENTION_DAYS,
    ActionType,
    AuditEvent,
    PurgeResult,
    RetentionMode,
    RetentionPolicy,
    RetentionResolution,
)
from .db import INSERT_SQL, connect, event_to_row, to_storage_ts, utcnow
from .errors import (
    E_PURGE_DISABLED,
    E_PURGE_FAILED,
    E_RETENTION_BELOW_BASELINE,
    E_RETENTION_INVALID,
    ERROR_SUMMARIES,
)
from .writer import new_event_id


def resolve_policy(
    retention_days: int | None = None,
    mode: str | RetentionMode = RetentionMode.FIXED,
    *,
    shorten_override: bool = False,
    shorten_override_reason: str | None = None,
) -> RetentionResolution:
    """Turn raw config values into a `RetentionPolicy`, or into an error explaining why not.

    Errors are data (`docs/PRINCIPLES.md` §4.1): a bad retention setting is reported, never
    raised, and never silently corrected to something the owner did not ask for.
    """
    try:
        resolved_mode = RetentionMode(mode)
    except ValueError:
        return RetentionResolution(
            error=E_RETENTION_INVALID,
            error_detail=f"retention_mode must be 'fixed' or 'indefinite', got {mode!r}",
        )

    days = DEFAULT_RETENTION_DAYS if retention_days is None else int(retention_days)
    if resolved_mode is RetentionMode.FIXED and days < 1:
        return RetentionResolution(
            error=E_RETENTION_INVALID,
            error_detail=f"retention_days must be at least 1 in fixed mode, got {days}",
        )
    # The baseline gate applies to `fixed` mode only. `indefinite` never purges anything, so
    # it retains *more* than the BIR baseline regardless of what `retention_days` happens to
    # say — refusing it because a stale, unused day count is below 3650 would refuse the one
    # setting that cannot possibly under-retain, and would contradict this module's own
    # docstring ("Raising it, or switching to `indefinite`, is always permitted").
    below_baseline = resolved_mode is RetentionMode.FIXED and days < DEFAULT_RETENTION_DAYS
    if below_baseline and not shorten_override:
        return RetentionResolution(
            error=E_RETENTION_BELOW_BASELINE,
            error_detail=(
                f"{ERROR_SUMMARIES[E_RETENTION_BELOW_BASELINE]} (requested {days} days, "
                f"baseline {DEFAULT_RETENTION_DAYS})"
            ),
        )
    if below_baseline and not (shorten_override_reason or "").strip():
        return RetentionResolution(
            error=E_RETENTION_BELOW_BASELINE,
            error_detail=(
                "an override shortening retention below the BIR baseline must carry a "
                "stated reason, which is itself recorded as a config-change audit event"
            ),
        )

    return RetentionResolution(
        policy=RetentionPolicy(
            retention_days=days,
            mode=resolved_mode,
            shorten_override=shorten_override and below_baseline,
            shorten_override_reason=shorten_override_reason,
        )
    )


def horizon(policy: RetentionPolicy, now: datetime | None = None) -> datetime | None:
    """The cutoff: events strictly older than this are purgeable. `None` in indefinite mode."""
    if policy.mode is RetentionMode.INDEFINITE:
        return None
    return (now or utcnow()) - timedelta(days=policy.retention_days)


class RetentionPurge:
    """The one deletion path. Its whole public surface is `purge()`.

    It deliberately cannot be asked to delete a specific event: `purge()` takes a policy and
    an actor, and derives its own `WHERE` clause from the policy's age horizon. There is no
    parameter through which a caller could name a row.
    """

    #: Never purged, regardless of age — see the module docstring.
    EXEMPT_ACTIONS: tuple[ActionType, ...] = (ActionType.RETENTION_PURGE_EXECUTED,)

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = connect(db_path, profile="purge")

    async def purge(
        self,
        policy: RetentionPolicy,
        actor_user_id: str = "system",
        now: datetime | None = None,
    ) -> PurgeResult:
        cutoff = horizon(policy, now)
        if cutoff is None:
            return PurgeResult(
                purged=0, error=E_PURGE_DISABLED, error_detail=ERROR_SUMMARIES[E_PURGE_DISABLED]
            )
        try:
            return await asyncio.to_thread(self._purge_blocking, policy, cutoff, actor_user_id)
        except sqlite3.DatabaseError as exc:
            return PurgeResult(
                horizon=cutoff,
                error=E_PURGE_FAILED,
                error_detail=f"{type(exc).__name__}: {exc}",
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------- blocking half
    def _purge_blocking(
        self, policy: RetentionPolicy, cutoff: datetime, actor_user_id: str
    ) -> PurgeResult:
        exempt = ",".join("?" * len(self.EXEMPT_ACTIONS))
        # Normalised the same way the stored column is, so the horizon comparison is a
        # comparison of instants rather than of however each caller happened to spell one.
        params = [to_storage_ts(cutoff), *(a.value for a in self.EXEMPT_ACTIONS)]
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM audit_events WHERE occurred_at < ?"
                f" AND action_type NOT IN ({exempt})",
                params,
            )
            purged = cur.rowcount or 0
            self._conn.commit()

            if purged == 0:
                # Nothing removed, nothing to account for. Recording a no-op purge every
                # sweep would bury the records that matter under ones that did not.
                return PurgeResult(purged=0, horizon=cutoff)

            # Recorded *after* the delete, deliberately: a record claiming a purge that did
            # not happen is worse evidence than a purge whose record failed loudly, and the
            # failure below is reported rather than swallowed.
            record = AuditEvent(
                event_id=new_event_id(),
                action_type=ActionType.RETENTION_PURGE_EXECUTED,
                actor_user_id=actor_user_id,
                occurred_at=utcnow(),
                reason=(
                    f"retention policy applied: {policy.retention_days} days "
                    f"({policy.mode.value})"
                ),
                details=FrozenDict({
                    "purged_count": purged,
                    "horizon": cutoff.isoformat(),
                    "retention_days": policy.retention_days,
                    "shorten_override": policy.shorten_override,
                }),
            )
            try:
                self._conn.execute(INSERT_SQL, event_to_row(record))
                self._conn.commit()
            except sqlite3.DatabaseError as exc:
                return PurgeResult(
                    purged=purged,
                    horizon=cutoff,
                    error=E_PURGE_FAILED,
                    error_detail=(
                        f"{purged} events were purged but the record of the purge could not "
                        f"be written: {exc}"
                    ),
                )
        return PurgeResult(purged=purged, horizon=cutoff)


__all__ = ["RetentionPurge", "horizon", "resolve_policy"]

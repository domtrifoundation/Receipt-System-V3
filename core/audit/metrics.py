"""What this API reports about itself to Health and Telemetrees.

Deliberately small. Audit's volume is low by definition — privileged actions are rare — so
there is no hot path here to instrument and no per-call timing worth collecting; that is
Logs API's job, for operational trace. What is genuinely worth exposing is the shape of the
log itself: how much of it there is, how far back it reaches, and how much of it is sitting
past the retention horizon waiting for the next sweep.

Like `query.py`, this opens a `read`-profile connection: it is structurally incapable of
writing, not merely written so as not to. Every failure degrades to a metrics snapshot
carrying `.error` rather than taking down the caller (`docs/PRINCIPLES.md` §4.1, §4.4) — a
monitoring read must never be able to disturb the thing it is monitoring.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from common.frozen_dict import FrozenDict

from .contracts import AuditMetrics, RetentionPolicy
from .db import connect, database_bytes, to_storage_ts
from .errors import E_READ_FAILED
from .retention import horizon


class AuditMetricsReader:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = connect(db_path, profile="read")

    async def snapshot(
        self, policy: RetentionPolicy | None = None, now: datetime | None = None
    ) -> AuditMetrics:
        try:
            return await asyncio.to_thread(self._snapshot_blocking, policy, now)
        except (sqlite3.DatabaseError, ValueError, TypeError) as exc:
            # `ValueError` covers `datetime.fromisoformat` on a row whose timestamp this
            # build cannot parse. A monitoring read must never be able to raise across the
            # boundary of the thing it is monitoring (`docs/PRINCIPLES.md` §4.1, §4.4).
            return AuditMetrics(error=E_READ_FAILED, error_detail=f"{type(exc).__name__}: {exc}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _snapshot_blocking(
        self, policy: RetentionPolicy | None, now: datetime | None
    ) -> AuditMetrics:
        with self._lock:
            totals = self._conn.execute(
                "SELECT COUNT(*) AS n, MIN(occurred_at) AS oldest, MAX(occurred_at) AS newest"
                " FROM audit_events"
            ).fetchone()
            by_action = self._conn.execute(
                "SELECT action_type, COUNT(*) AS n FROM audit_events GROUP BY action_type"
            ).fetchall()

            past = 0
            cutoff = horizon(policy, now) if policy is not None else None
            if cutoff is not None:
                past = int(
                    self._conn.execute(
                        "SELECT COUNT(*) AS n FROM audit_events WHERE occurred_at < ?",
                        (to_storage_ts(cutoff),),
                    ).fetchone()["n"]
                )

        def parse(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        return AuditMetrics(
            total_events=int(totals["n"]),
            # FrozenDict, not dict: this crosses an API boundary on a frozen contract, and a
            # frozen dataclass holding a plain dict is only shallowly immutable (§2.1).
            events_by_action=FrozenDict({r["action_type"]: int(r["n"]) for r in by_action}),
            oldest_occurred_at=parse(totals["oldest"]),
            newest_occurred_at=parse(totals["newest"]),
            events_past_horizon=past,
            database_bytes=database_bytes(self._conn, self._path),
        )


__all__ = ["AuditMetricsReader"]

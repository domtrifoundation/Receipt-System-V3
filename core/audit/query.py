"""Staff/owner-only read access to the audit log (§4).

**Read access is staff/owner only, never client role.** This is privileged-action visibility
by definition, not general-purpose data a client-role user has a claim to even about
themselves — a client learning "staff member X accessed my folder on date Y for reason Z" is
already surfaced to them directly by Notifications, per Auth's own break-glass design, and
this API deliberately does not serve that same information a second way.

The role check **fails closed** (`docs/PRINCIPLES.md` §4.2): an unrecognised role, an empty
string, or `None` is denied. There is no default-permit branch anywhere in this file. What
the check does *not* do is trust a role the caller asserts about itself — `service.py`
resolves the role from the caller's own session before it reaches here.

This module opens its own connection under `db.py`'s `read` profile, which permits `SELECT`
and nothing else — not even `INSERT`. A read path that is structurally incapable of writing
is worth more than one that merely never does (`docs/PRINCIPLES.md` §4.5).
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path

from .contracts import (
    READER_ROLES,
    AuditEvent,
    AuditQueryFilter,
    AuditQueryResult,
)
from .db import connect, rows_to_events, to_storage_ts
from .errors import E_READ_FAILED, E_ROLE_FORBIDDEN, ERROR_SUMMARIES

#: A read is capped regardless of what the caller asks for, so a mis-set limit cannot pull a
#: decade of records into one response. A caller wanting more pages through `offset`.
MAX_LIMIT = 1000


def build_where(f: AuditQueryFilter) -> tuple[str, list]:
    """Compose the WHERE clause and its bound parameters.

    Every value is bound, never interpolated. The one piece of SQL built from input is the
    `IN (?,?,…)` placeholder run, whose length comes from the filter and whose contents are
    still bound — worth noting explicitly since string-built SQL is the thing to look for
    when reviewing this file.
    """
    clauses: list[str] = []
    params: list = []
    if f.action_types:
        clauses.append(f"action_type IN ({','.join('?' * len(f.action_types))})")
        params.extend(a.value for a in f.action_types)
    if f.actor_user_id:
        clauses.append("actor_user_id = ?")
        params.append(f.actor_user_id)
    if f.target_user_id:
        clauses.append("target_user_id = ?")
        params.append(f.target_user_id)
    if f.occurred_after is not None:
        clauses.append("occurred_at >= ?")
        params.append(to_storage_ts(f.occurred_after))
    if f.occurred_before is not None:
        clauses.append("occurred_at < ?")
        params.append(to_storage_ts(f.occurred_before))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def role_permitted(role: str | None) -> bool:
    """Fail closed. `None`, `""`, `"client"` and anything unrecognised are all denied."""
    return bool(role) and role in READER_ROLES


class AuditQuery:
    """Read-side access. Has no write method of any kind, and its connection cannot write."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = connect(db_path, profile="read")

    # ------------------------------------------------------------- public API
    async def fetch(
        self, filter_: AuditQueryFilter, requester_role: str | None
    ) -> AuditQueryResult:
        """Return matching events, newest first, plus the unpaged total.

        Errors are data here too — a forbidden role and a failed read are both reported on
        the result rather than raised (`docs/PRINCIPLES.md` §4.1). Audit has no equivalent of
        Auth's raise-loudly carve-out: this call is a staff member looking at history, and a
        denied read is a business outcome, not a session failure.
        """
        if not role_permitted(requester_role):
            return AuditQueryResult(
                error=E_ROLE_FORBIDDEN,
                error_detail=(
                    f"{ERROR_SUMMARIES[E_ROLE_FORBIDDEN]} (requesting role: "
                    f"{requester_role or 'none'})"
                ),
            )
        try:
            return await asyncio.to_thread(self._fetch_blocking, filter_)
        except (sqlite3.DatabaseError, ValueError, TypeError) as exc:
            # `ValueError`/`TypeError` are not paranoia: decoding a row runs
            # `ActionType(...)`, `json.loads` and `datetime.fromisoformat` over data written
            # by *some* build of this package, not necessarily this one. A row carrying an
            # `ActionType` added in a newer release, or a timestamp a future change writes
            # differently, would otherwise raise straight across the gRPC boundary — the one
            # thing `docs/PRINCIPLES.md` §4.1 says never happens here.
            return AuditQueryResult(
                error=E_READ_FAILED, error_detail=f"{type(exc).__name__}: {exc}"
            )

    async def get(self, event_id: str, requester_role: str | None) -> AuditQueryResult:
        """Fetch one event by id, plus every event that corrects it.

        Returned as one ordered result rather than a bare event because a corrected entry
        read without its corrections is misleading evidence, and the read path is where that
        is cheapest to get right (§3.2 — corrections are new events, never edits).
        """
        if not role_permitted(requester_role):
            return AuditQueryResult(
                error=E_ROLE_FORBIDDEN, error_detail=ERROR_SUMMARIES[E_ROLE_FORBIDDEN]
            )
        try:
            return await asyncio.to_thread(self._get_blocking, event_id)
        except (sqlite3.DatabaseError, ValueError, TypeError) as exc:  # see `fetch` above
            return AuditQueryResult(
                error=E_READ_FAILED, error_detail=f"{type(exc).__name__}: {exc}"
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------- blocking half
    def _fetch_blocking(self, f: AuditQueryFilter) -> AuditQueryResult:
        where, params = build_where(f)
        limit = max(1, min(f.limit or 1, MAX_LIMIT))
        offset = max(0, f.offset)
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM audit_events{where}", params
            ).fetchone()["n"]
            rows = self._conn.execute(
                f"SELECT * FROM audit_events{where} ORDER BY occurred_at DESC, seq DESC"
                " LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return AuditQueryResult(events=rows_to_events(rows), total_matching=int(total))

    def _get_blocking(self, event_id: str) -> AuditQueryResult:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_events WHERE event_id = ? OR corrects_event_id = ?"
                " ORDER BY occurred_at ASC, seq ASC",
                (event_id, event_id),
            ).fetchall()
        events: tuple[AuditEvent, ...] = rows_to_events(rows)
        return AuditQueryResult(events=events, total_matching=len(events))


__all__ = ["MAX_LIMIT", "AuditQuery", "build_where", "role_permitted"]

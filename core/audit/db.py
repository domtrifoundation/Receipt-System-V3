"""The one place `sqlite3` is imported in this package — schema, connections, authorizers.

**Why this file exists when the deep-dive's §2 layout does not list it**: §3.2's resolved
mechanism (open questions, second bullet) is `sqlite3.Connection.set_authorizer()`, and
three modules need connections with three genuinely different authorizer profiles —
`writer.py` (insert and read, nothing else), `query.py` (read only), `retention.py` (the one
narrow delete path). Putting the connection factory in `writer.py` would mean `query.py`
imports the writer to get a *read* handle, which is exactly backwards; duplicating it three
ways would mean three places the append-only guarantee could be got wrong. It also satisfies
`docs/PRINCIPLES.md` §1.3 at library granularity: `sqlite3` is an external library, so it
sits behind one small internal adapter rather than being imported at scattered call sites.

**The authorizer is the real enforcement, not a comment describing an intention.** SQLite has
no statement-level GRANT system, so "INSERT-only connection" is implemented as a connection
that registers a callback denying every operation outside an explicit allow-list, checked
before the statement executes. Verified against a real 3.14 interpreter, not assumed: an
`UPDATE`, `DELETE`, `DROP TABLE`, `ALTER TABLE`, `ATTACH`, `CREATE TABLE` or `PRAGMA` issued
on an append-profile connection raises `sqlite3.DatabaseError("not authorized")`.

Two details that are easy to get wrong and are deliberate here:

1. **The authorizer is installed after the schema is created.** A deny-by-default authorizer
   would refuse the `CREATE TABLE` that sets the database up in the first place.
2. **No `AUTOINCREMENT` on the sequence column.** `AUTOINCREMENT` makes SQLite maintain the
   `sqlite_sequence` table, which means every INSERT also issues an INSERT/UPDATE against
   *that* table — an UPDATE the authorizer would correctly deny, breaking ordinary appends.
   A plain `INTEGER PRIMARY KEY` is a rowid alias and is monotonic for our purposes without
   any of that.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from common.frozen_dict import FrozenDict

from .contracts import ActionType, AuditEvent

#: One table. Audit's whole scope is one kind of record, and a second table here would be
#: the beginning of the catch-all the deep-dive's §1 exists to prevent. Typed/learned/schema
#: data is Architect's, never this API's (`docs/PRINCIPLES.md` §3.4) — nothing below is
#: taxonomy, it is a flat record of things that happened.
SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    seq               INTEGER PRIMARY KEY,
    event_id          TEXT NOT NULL UNIQUE,
    action_type       TEXT NOT NULL,
    actor_user_id     TEXT NOT NULL,
    target_user_id    TEXT,
    reason            TEXT,
    details           TEXT NOT NULL DEFAULT '{}',
    occurred_at       TEXT NOT NULL,
    corrects_event_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_occurred_at ON audit_events(occurred_at);
CREATE INDEX IF NOT EXISTS ix_audit_action ON audit_events(action_type, occurred_at);
CREATE INDEX IF NOT EXISTS ix_audit_actor ON audit_events(actor_user_id, occurred_at);
CREATE INDEX IF NOT EXISTS ix_audit_target ON audit_events(target_user_id, occurred_at);
"""

AUDIT_TABLE = "audit_events"

#: Operations every profile needs to function at all: reading rows back, running a statement
#: inside a transaction, and calling scalar SQL functions such as `count()`.
_BASE_ALLOWED: frozenset[int] = frozenset({
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_TRANSACTION,
    sqlite3.SQLITE_FUNCTION,
})

#: Profile name -> the operation codes it adds on top of `_BASE_ALLOWED`. `FrozenDict` per
#: `docs/PRINCIPLES.md` §2.1.1: a module-level constant table, read from several threads,
#: that nothing should ever write. Note `SQLITE_UPDATE` appears in no profile at all — an
#: audit row is never modified by any connection this package can open.
PROFILE_EXTRA_OPS: FrozenDict = FrozenDict({
    "append": frozenset({sqlite3.SQLITE_INSERT}),
    "read": frozenset(),
    # The single narrow exception, and the reason it is narrow: `retention.py` is the only
    # module that opens this profile, it issues exactly one parameterised DELETE bounded by
    # an age horizon, and it appends a record of having done so (which is why INSERT is
    # here too). See that module's docstring.
    "purge": frozenset({sqlite3.SQLITE_DELETE, sqlite3.SQLITE_INSERT}),
})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_storage_ts(value: datetime) -> str:
    """Normalise a timestamp to a UTC ISO-8601 string before it is stored or compared.

    **This is load-bearing, not tidiness.** `occurred_at` is stored as TEXT and every
    comparison SQLite makes against it — the retention horizon's `<`, the query filter's
    range bounds, `ORDER BY occurred_at DESC` — is a *lexical* string comparison. An event
    recorded as `2016-07-30T14:04:20+08:00` and a horizon expressed as
    `2016-07-30T07:04:20+00:00` are the same instant one hour apart, but the first string
    sorts *after* the second, so the row would be silently retained past its horizon and
    would sort out of order against UTC rows. Normalising every timestamp to UTC at the one
    place it enters storage is what makes the lexical comparison agree with the real
    chronology; comparing offsets in SQL is not an option worth taking instead.

    A naive datetime is treated as UTC rather than rejected: this API records that a
    privileged action happened, and refusing the record because a caller forgot a `tzinfo`
    would lose the evidence over a formatting detail (`docs/PRINCIPLES.md` §4.4).
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def default_db_path() -> Path:
    """Audit's own small top-level SQLite database (§3.1).

    Deliberately *not* inside any per-user Persistence folder: audit events span every user
    and every staff action, so they are cross-tenancy infrastructure the same way Auth's
    sessions are. It sits beside Auth's own database and Architect's moderation-queue
    database in the top-level installation directory — three separate databases with three
    non-overlapping scopes, never one shared catch-all (`docs/PRINCIPLES.md` §1.6).

    `RESIBO_TOP_LEVEL` is how Supervisor tells a service where that shared top level is. The
    fallback resolves outside the repository, never into `data/`, because a bare developer
    checkout must stay runnable without the repo becoming a home for real records.
    """
    top = os.environ.get("RESIBO_TOP_LEVEL")
    base = Path(top) if top else Path.home() / ".resibo"
    return base / "audit.sqlite"


def make_authorizer(profile: str) -> Callable[..., int]:
    """Build the deny-by-default authorizer callback for one connection profile.

    Deny-by-default rather than deny-a-blocklist: a blocklist has to be updated every time
    SQLite gains an operation code, and the failure mode of forgetting is that the new
    operation is permitted. Here the failure mode of forgetting is that something legitimate
    stops working loudly, which is the correct direction for this particular API.
    """
    allowed = _BASE_ALLOWED | PROFILE_EXTRA_OPS[profile]
    writes = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE}

    def authorizer(action: int, arg1, arg2, db_name, trigger_name) -> int:
        if action not in allowed:
            return sqlite3.SQLITE_DENY
        # A permitted write is still only permitted against the audit table itself, so a
        # profile that may INSERT cannot reach any other table that might later exist in
        # this database file.
        if action in writes and arg1 != AUDIT_TABLE:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return authorizer


def connect(path: Path | str | None, profile: str) -> sqlite3.Connection:
    """Open a connection under one of the profiles in `PROFILE_EXTRA_OPS`.

    Schema creation and `PRAGMA` both run first, before the authorizer is installed — see
    the module docstring for why the ordering is not incidental.
    """
    if profile not in PROFILE_EXTRA_OPS:
        raise ValueError(f"unknown connection profile {profile!r}")
    resolved = Path(path) if path is not None else default_db_path()
    is_memory = str(resolved) == ":memory:"
    if not is_memory:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if not is_memory:
        # WAL so a reader profile and the writer profile do not block each other.
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    conn.set_authorizer(make_authorizer(profile))
    return conn


# ------------------------------------------------------------- row <-> event


def event_to_row(event: AuditEvent) -> tuple:
    """`details` is serialised with `dict(...)` first because `FrozenDict` is not a `dict`
    subclass on Python 3.15+ and `json.dumps` would otherwise refuse it — the same
    not-a-dict-subclass gotcha `common/frozen_dict.py` documents, showing up somewhere
    other than an `isinstance` check."""
    return (
        event.event_id,
        event.action_type.value,
        event.actor_user_id,
        event.target_user_id,
        event.reason,
        json.dumps(dict(event.details), default=str, sort_keys=True),
        to_storage_ts(event.occurred_at),
        event.corrects_event_id,
    )


INSERT_SQL = (
    "INSERT INTO audit_events (event_id, action_type, actor_user_id, target_user_id,"
    " reason, details, occurred_at, corrects_event_id) VALUES (?,?,?,?,?,?,?,?)"
)


def row_to_event(row: sqlite3.Row) -> AuditEvent:
    return AuditEvent(
        event_id=row["event_id"],
        action_type=ActionType(row["action_type"]),
        actor_user_id=row["actor_user_id"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        target_user_id=row["target_user_id"],
        reason=row["reason"],
        details=FrozenDict(json.loads(row["details"])),
        corrects_event_id=row["corrects_event_id"],
    )


def rows_to_events(rows: Iterable[sqlite3.Row]) -> tuple[AuditEvent, ...]:
    return tuple(row_to_event(r) for r in rows)


def database_bytes(conn: sqlite3.Connection, path: Path | str | None) -> int:
    """On-disk size, or 0 for an in-memory database. Best-effort — a metrics read that
    cannot size the file degrades to 0 rather than failing the whole snapshot (§4.4)."""
    resolved = Path(path) if path is not None else default_db_path()
    if str(resolved) == ":memory:":
        return 0
    try:
        return resolved.stat().st_size
    except OSError:
        return 0


__all__ = [
    "AUDIT_TABLE",
    "INSERT_SQL",
    "PROFILE_EXTRA_OPS",
    "SCHEMA",
    "connect",
    "database_bytes",
    "default_db_path",
    "event_to_row",
    "make_authorizer",
    "row_to_event",
    "rows_to_events",
    "to_storage_ts",
    "utcnow",
]

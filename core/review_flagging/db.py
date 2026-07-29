"""The one place `sqlite3` is imported in this package — schema, connection, row mapping.

**Not in the deep-dive's §2 package layout, added for the same reason
`core/audit/db.py` and `core/notifications/db.py` exist.** A flag is genuine instance data —
one row per flag raised against a receipt — and this package's own write boundary is
`core/review_flagging/` only; adding a table to Persistence's own schema is that API's move
to make, the identical situation `core/audit/CLAUDE.md` already documents for Agent Control's
own `agent_audit` table and `core/notifications/CLAUDE.md` documents for its own per-user
tables. So this file opens a small, **cross-tenancy** database of its own, at the identical
`RESIBO_TOP_LEVEL` top-level convention `core/audit/db.py` already uses.

**Cross-tenancy, not per-user, and that is a deliberate choice distinct from Notifications'
own per-user split.** A flag belongs to one user's receipt, but the *staff queue* that works
it (§8's own resolved routing policy: "a shared open queue, self-assign") has to be queried
across every user's flags at once — "every open flag, any staff member" is not expressible
against a store partitioned per user without querying every user's database in turn. Audit's
own `audit_events` table faces the identical shape (one row references one user; the log as a
whole is staff/owner infrastructure spanning all of them) and resolves it the same way: one
small top-level database, not one per user.

No authorizer profile here unlike Audit's own `db.py` — this table's own rows are mutated by
design (a flag's `status`/`assigned_to`/`resolved_at` genuinely change in place as it moves
through its lifecycle), so there is no append-only guarantee to enforce structurally the way
Audit's is. What *is* enforced is entirely in `lifecycle.py`: every transition is checked
against `contracts.VALID_TRANSITIONS` before a single `UPDATE` is issued.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from common.frozen_dict import FrozenDict

from .contracts import Flag, FlagStatus

#: One table. This package's whole scope is the flag lifecycle (`docs/PRINCIPLES.md` §3.4 —
#: no taxonomy or schema data of its own); nothing below is a definition, it is a flat record
#: of flag instances raised against receipts.
SCHEMA = """
CREATE TABLE IF NOT EXISTS flags (
    seq             INTEGER PRIMARY KEY,
    flag_id         TEXT NOT NULL UNIQUE,
    flag_type       TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    receipt_id      TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    assigned_to     TEXT,
    resolved_at     TEXT,
    resolved_by     TEXT,
    resolution_note TEXT NOT NULL DEFAULT '',
    payload         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_flags_status ON flags(status, created_at);
CREATE INDEX IF NOT EXISTS ix_flags_receipt ON flags(receipt_id);
CREATE INDEX IF NOT EXISTS ix_flags_user ON flags(user_id);
CREATE INDEX IF NOT EXISTS ix_flags_assigned ON flags(assigned_to);
"""

FLAGS_TABLE = "flags"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_storage_ts(value: datetime) -> str:
    """Normalise a timestamp to UTC ISO-8601 before it is stored or compared.

    `created_at`/`resolved_at` are TEXT columns, so `ORDER BY created_at` and any future range
    filter are lexical string comparisons — the identical load-bearing reasoning
    `core/audit/db.py::to_storage_ts` states for its own `occurred_at` column. A naive
    datetime is treated as UTC rather than rejected, matching that same precedent
    (`docs/PRINCIPLES.md` §4.4): losing a flag's timestamp over a missing `tzinfo` would be
    the wrong trade.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def default_db_path() -> Path:
    """This API's own small top-level SQLite database.

    Deliberately not inside any per-user Persistence folder (see this module's own
    docstring on why flags are cross-tenancy infrastructure). `RESIBO_TOP_LEVEL` is how
    Supervisor tells a service where the shared top level is; the fallback resolves outside
    the repository so a bare developer checkout stays runnable without becoming a home for
    real records (`docs/PRINCIPLES.md` §1.6).
    """
    top = os.environ.get("RESIBO_TOP_LEVEL")
    base = Path(top) if top else Path.home() / ".resibo"
    return base / "review_flagging.sqlite"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    resolved = Path(path) if path is not None else default_db_path()
    is_memory = str(resolved) == ":memory:"
    if not is_memory:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if not is_memory:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ------------------------------------------------------------------- row <-> flag

INSERT_SQL = (
    "INSERT INTO flags (flag_id, flag_type, user_id, receipt_id, status, created_by,"
    " created_at, assigned_to, resolved_at, resolved_by, resolution_note, payload)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
)

UPDATE_SQL = (
    "UPDATE flags SET status = ?, assigned_to = ?, resolved_at = ?, resolved_by = ?,"
    " resolution_note = ? WHERE flag_id = ?"
)


def flag_to_insert_row(flag: Flag) -> tuple:
    """`payload` is serialised with `dict(...)` first because `FrozenDict` is not a `dict`
    subclass on Python 3.15+ and `json.dumps` would otherwise refuse it — the same gotcha
    `core/audit/db.py::event_to_row` documents for its own dict-typed field."""
    return (
        flag.flag_id,
        flag.flag_type,
        flag.user_id,
        flag.receipt_id,
        flag.status.value,
        flag.created_by,
        to_storage_ts(flag.created_at),
        flag.assigned_to,
        to_storage_ts(flag.resolved_at) if flag.resolved_at else None,
        flag.resolved_by,
        flag.resolution_note,
        json.dumps(dict(flag.payload), default=str, sort_keys=True),
    )


def row_to_flag(row: sqlite3.Row) -> Flag:
    return Flag(
        flag_id=row["flag_id"],
        flag_type=row["flag_type"],
        user_id=row["user_id"],
        receipt_id=row["receipt_id"],
        status=FlagStatus(row["status"]),
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
        assigned_to=row["assigned_to"],
        resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
        resolved_by=row["resolved_by"],
        resolution_note=row["resolution_note"] or "",
        payload=FrozenDict(json.loads(row["payload"])),
    )


__all__ = [
    "FLAGS_TABLE",
    "INSERT_SQL",
    "SCHEMA",
    "UPDATE_SQL",
    "connect",
    "default_db_path",
    "flag_to_insert_row",
    "row_to_flag",
    "to_storage_ts",
    "utcnow",
]

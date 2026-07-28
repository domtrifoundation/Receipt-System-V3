"""The one place `sqlite3` is imported in this package — per-user connections and schema.

**Not in the deep-dive's §2 package layout, and the reason is worth stating precisely.** §3
says storage "lives in each user's own Persistence database (a `notifications` table)... no
separate top-level database needed here." That is the right target shape: Persistence already
owns all disk access (its own `CLAUDE.md`), and a `notifications` table living inside each
user's existing `canonical.sqlite` would mean one fewer file per user, not a second store next
to it. **It cannot be built that way today**: `core/persistence/db/schema.py` (Wave 1, already
implemented) defines no `notifications` table, and this task's own working boundary is
`core/notifications/` and its tests only — adding a table to Persistence's schema is that
API's own change to make, the identical situation `core/audit/CLAUDE.md` already documents for
Agent Control's `agent_audit` table ("a bounded exception taken before this API existed...
it is that API's move to make, not something to reach across and do from here").

So: this module opens a **sibling** SQLite file, not a table inside Persistence's own database,
at the *identical* per-user path convention Persistence's own
`core/persistence/db/connection.py::default_db_path` uses — same `RESIBO_TOP_LEVEL`
environment variable, same `users/<user_id>/` directory, same reasoning
(`docs/PRINCIPLES.md` §1.6, §2.4, §4.5: per-user data lives in the top-level installation
directory, and the per-user *folder* is itself the isolation boundary, not a permission check
enforced only in application code). This is deliberately **not** an import of
`core.persistence.db.connection` — `docs/PRINCIPLES.md` §1.1 confines what one package imports
from another to its `contracts.py`, and `db/connection.py` is not that module — so the path
convention is reimplemented here, the same way `core/audit/db.py::default_db_path` and
`core/logs/paths.py::default_log_root` each independently apply the identical
`RESIBO_TOP_LEVEL` convention rather than importing one another's path helper. When Persistence
grows a `notifications` table, migrating this file's two tables into it is a data migration,
not an architectural one — the path convention, the row shapes and the per-user isolation
boundary are already identical.

Two tables, one file per user: `notifications` (§3) and `channel_preferences` (§5). One file
rather than two because both are genuinely this user's own small, low-volume records, and a
second per-user file would double the open-file/connection bookkeeping for no isolation gain.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .contracts import ChannelPreference, Notification

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    category        TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    reference       TEXT,
    read_at         TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
    ON notifications(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS channel_preferences (
    user_id          TEXT NOT NULL,
    channel          TEXT NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 0,
    contact_override TEXT,
    PRIMARY KEY (user_id, channel)
);
"""


def default_top_level() -> Path:
    """`RESIBO_TOP_LEVEL`, or the same bare-checkout fallback every other Core API's own
    per-installation path helper uses (`core/audit/db.py`, `core/logs/paths.py`,
    `core/persistence/db/connection.py`) — never a path inside the repository itself."""
    top = os.environ.get("RESIBO_TOP_LEVEL")
    return Path(top) if top else Path.home() / ".resibo"


def default_db_path(user_id: str, *, top_level: Path | str | None = None) -> Path:
    """The per-user notifications database path — a sibling of Persistence's own
    `canonical.sqlite` under the identical `users/<user_id>/` directory, per this module's own
    docstring on why this is not a table inside that file today."""
    base = Path(top_level) if top_level else default_top_level()
    return base / "users" / user_id / "notifications.sqlite"


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (creating if needed) one user's notifications database.

    WAL mode, matching every other per-user or cross-tenant store in this project
    (`core/persistence/db/connection.py`, `core/audit/db.py`) — readers and writers stop
    blocking each other at the cost of the WAL file's own small extra I/O.
    """
    resolved = Path(path)
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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_storage_ts(value: datetime) -> str:
    """Normalise to a UTC ISO-8601 string before storage or comparison.

    **Load-bearing, not tidiness** — `created_at`/`read_at` are TEXT columns, so
    `ORDER BY created_at DESC` is a *lexical* comparison. The identical reasoning
    `core/audit/db.py::to_storage_ts` documents at length: two different offsets for the same
    instant sort differently as strings even though they compare equal as datetimes. A naive
    value is treated as UTC rather than rejected — refusing to store a notification because a
    caller forgot a `tzinfo` would be the wrong trade (`docs/PRINCIPLES.md` §4.4).
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def from_storage_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


# ------------------------------------------------------------- row <-> contract


def notification_to_row(n: Notification) -> tuple:
    return (
        n.notification_id,
        n.user_id,
        n.category,
        n.title,
        n.body,
        n.reference,
        to_storage_ts(n.read_at) if n.read_at is not None else None,
        to_storage_ts(n.created_at),
    )


INSERT_NOTIFICATION_SQL = (
    "INSERT INTO notifications (notification_id, user_id, category, title, body, reference,"
    " read_at, created_at) VALUES (?,?,?,?,?,?,?,?)"
)


def row_to_notification(row: sqlite3.Row) -> Notification:
    return Notification(
        notification_id=row["notification_id"],
        user_id=row["user_id"],
        category=row["category"],
        title=row["title"],
        body=row["body"],
        reference=row["reference"],
        read_at=from_storage_ts(row["read_at"]),
        created_at=from_storage_ts(row["created_at"]) or utcnow(),
    )


def row_to_preference(row: sqlite3.Row) -> ChannelPreference:
    return ChannelPreference(
        user_id=row["user_id"],
        channel=row["channel"],
        enabled=bool(row["enabled"]),
        contact_override=row["contact_override"],
    )


__all__ = [
    "INSERT_NOTIFICATION_SQL",
    "SCHEMA",
    "connect",
    "default_db_path",
    "default_top_level",
    "from_storage_ts",
    "notification_to_row",
    "row_to_notification",
    "row_to_preference",
    "to_storage_ts",
    "utcnow",
]

"""`TaskStore` — per-user schedule storage through Persistence API's own primitives, never a
second SQLite wrapper of this package's own invention.

**Why this file exists when the deep-dive's §2 package layout does not list it**: §3 says a
`UserScheduledTask` "lives in the owning user's own Persistence database — this is per-user
preference data ... not infrastructure this sub-API stores itself." Persistence's own
`CLAUDE.md` states the load-bearing rule this follows from directly: **"Persistence owns all
disk access — nothing else in this system touches disk directly."** So this package does not
open its own `sqlite3.connect()` the way `core/groups/store.py` does for Auth's database —
Groups' data is cross-user infrastructure sitting beside Auth's own database, a genuinely
different placement decision (`docs/PRINCIPLES.md` §1.6) from a per-*user* preference that
belongs inside that same user's own canonical database. This module instead reuses
Persistence's own `Database` class (`core/persistence/db/connection.py`) — its WAL setup, its
single-writer-thread executor, its async/sync split — and extends that class's own schema
*extension point* (`Database.__init__`'s own `schema` keyword) with one additional table,
rather than duplicating any of that machinery.

**This reaches past `core.persistence.contracts` on purpose, and that is the one deliberate
exception in this build.** `docs/PRINCIPLES.md` §1.1 says `contracts.py` is the only module
another package imports from, but `Database` and `default_db_path` are not *contracts* —
they are the shared low-level primitive Persistence's own `CLAUDE.md` explicitly names as the
one path to disk in this whole system, and `contracts.py` does not (and, being types-only per
§1.1, structurally cannot) re-export a connection-holding class. Importing the primitive
directly is what "goes through Persistence API's primitives, not its own store" means
concretely; re-deriving a second WAL/executor implementation here to avoid the import would be
a straightforwardly worse outcome — a second, independently-maintained opinion about the exact
thing Persistence exists to centralize.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from core.persistence.db.connection import Database, default_db_path
from core.persistence.db.schema import SCHEMA as PERSISTENCE_SCHEMA

from .contracts import UserScheduledTask

#: This package's own additive schema fragment, appended to Persistence's own `SCHEMA` when
#: opening a user's database — never a replacement for it. `CREATE TABLE IF NOT EXISTS` is
#: the same idempotent, additive-only discipline `core/persistence/db/schema.py` already
#: documents for its own tables.
TASK_SCHEDULER_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_scheduled_tasks (
    task_id            TEXT PRIMARY KEY,
    created_by         TEXT NOT NULL,
    action             TEXT NOT NULL,
    action_params_json TEXT NOT NULL DEFAULT '{}',
    cron_expression    TEXT NOT NULL,
    enabled            INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user ON user_scheduled_tasks(created_by);
"""

_COMBINED_SCHEMA = PERSISTENCE_SCHEMA + TASK_SCHEDULER_SCHEMA

_INSERT_SQL = (
    "INSERT INTO user_scheduled_tasks (task_id, created_by, action, action_params_json,"
    " cron_expression, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)"
)
_UPDATE_SQL = (
    "UPDATE user_scheduled_tasks SET action = ?, action_params_json = ?, cron_expression = ?,"
    " enabled = ?, updated_at = ? WHERE task_id = ? AND created_by = ?"
)


def _task_to_row(task: UserScheduledTask) -> tuple:
    return (
        task.task_id, task.created_by, task.action,
        json.dumps(dict(task.action_params), default=str, sort_keys=True),
        task.cron_expression, int(task.enabled),
        task.created_at.isoformat(), task.updated_at.isoformat(),
    )


def _row_to_task(row) -> UserScheduledTask:
    from common.frozen_dict import FrozenDict

    return UserScheduledTask(
        task_id=row["task_id"], created_by=row["created_by"], action=row["action"],
        action_params=FrozenDict(json.loads(row["action_params_json"])),
        cron_expression=row["cron_expression"], enabled=bool(row["enabled"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class TaskStore:
    """One `Database` per user, opened on demand and cached — the same per-user isolation
    boundary every other Persistence-backed table already relies on (`docs/PRINCIPLES.md`
    §4.5): a bug in a role check elsewhere is a real problem, but it cannot reach across
    databases it never opened in the first place."""

    def __init__(self, top_level: Path | str | None = None) -> None:
        self._top_level = top_level
        self._dbs: dict[str, Database] = {}
        self._lock = threading.Lock()

    def _db_for(self, user_id: str) -> Database:
        with self._lock:
            db = self._dbs.get(user_id)
            if db is None:
                path = default_db_path(self._top_level, user_id)
                db = Database(path, schema=_COMBINED_SCHEMA)
                self._dbs[user_id] = db
            return db

    async def insert(self, task: UserScheduledTask) -> None:
        db = self._db_for(task.created_by)
        await db.run(lambda conn: conn.execute(_INSERT_SQL, _task_to_row(task)))

    async def get(self, user_id: str, task_id: str) -> UserScheduledTask | None:
        db = self._db_for(user_id)

        def _do(conn):
            return conn.execute(
                "SELECT * FROM user_scheduled_tasks WHERE task_id = ? AND created_by = ?",
                (task_id, user_id),
            ).fetchone()

        row = await db.run(_do)
        return _row_to_task(row) if row else None

    async def update(self, task: UserScheduledTask) -> bool:
        """`True` only if a row with this `(task_id, created_by)` pair actually existed —
        never creates one, the same "update means update" discipline Auth's own
        `UserDirectory.set_role` follows for a different table."""
        db = self._db_for(task.created_by)

        def _do(conn):
            cur = conn.execute(
                _UPDATE_SQL,
                (
                    task.action,
                    json.dumps(dict(task.action_params), default=str, sort_keys=True),
                    task.cron_expression, int(task.enabled), task.updated_at.isoformat(),
                    task.task_id, task.created_by,
                ),
            )
            return cur.rowcount > 0

        return await db.run(_do)

    async def delete(self, user_id: str, task_id: str) -> bool:
        db = self._db_for(user_id)

        def _do(conn):
            cur = conn.execute(
                "DELETE FROM user_scheduled_tasks WHERE task_id = ? AND created_by = ?",
                (task_id, user_id),
            )
            return cur.rowcount > 0

        return await db.run(_do)

    async def list_for_user(self, user_id: str) -> list[UserScheduledTask]:
        db = self._db_for(user_id)

        def _do(conn):
            return conn.execute(
                "SELECT * FROM user_scheduled_tasks WHERE created_by = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()

        rows = await db.run(_do)
        return [_row_to_task(r) for r in rows]

    async def count_for_user(self, user_id: str) -> int:
        """Every task counts against the tier cap (§10), enabled or not — a disabled task is
        still a slot the user is holding, not one available to a new task."""
        db = self._db_for(user_id)

        def _do(conn):
            return conn.execute(
                "SELECT COUNT(*) AS n FROM user_scheduled_tasks WHERE created_by = ?",
                (user_id,),
            ).fetchone()

        row = await db.run(_do)
        return int(row["n"]) if row else 0

    def close(self) -> None:
        with self._lock:
            for db in self._dbs.values():
                db.close()
            self._dbs.clear()


__all__ = ["TASK_SCHEDULER_SCHEMA", "TaskStore"]

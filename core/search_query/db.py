"""Per-user connection registry onto Persistence's own canonical SQLite files
(`v3-deepdive-21-search-query-api.md` §1's "this API is the query layer, Persistence is the
storage layer").

**Not in the deep-dive's own §2 package layout.** Added because *reading* Persistence's data
requires opening it, and the deep-dive is explicit that a separate synced copy would be
redundant infrastructure and a real consistency risk this API must not create (§1). This
module is Search/Query's own, independent SQLite connection onto the *same physical file*
Persistence's own process writes to — the identical "multiple connections, one file, under
WAL" mechanism `core/groups/store.py` already documents in full for Auth's own database,
never a shared in-memory object across the process boundary (`docs/PROCESS_TOPOLOGY.md`).

**Per-user, not per-instance.** Persistence isolates data by *folder*, one canonical database
per user (`core/persistence/db/connection.py`'s own `default_db_path`), not one shared
database with a `user_id` column doing the isolation (`docs/PRINCIPLES.md` §4.5 — structural
isolation over a permission check wherever both are available). Group-scoped search therefore
cannot be one SQL query with `user_id IN (...)`; it is one connection per member, fanned out
and merged in Python (`structured_query.py`). `default_db_path()` below is *re-derived* here,
matching Persistence's own convention, rather than importing `core.persistence.db.connection`
— `contracts.py` is the only module another package may import from
(`docs/PRINCIPLES.md` §1.1), and `db/connection.py` is Persistence's own internal file, not
its published contract. `core/groups/store.py`'s own docstring records the identical reasoning
for Auth's database.

**A real, load-bearing gap this file exists to close, not a design choice.** The deep-dive's
own §3 says `receipts_fts` and its sync triggers live in Persistence's database, populated "at
write time as part of the same transaction" — but `core/persistence/db/schema.py` does not yet
define them, and this task's own scope forbids touching `core/persistence/` to add them there.
`ensure_fts_schema()` (`fts_query.py`) provisions the virtual table and its triggers directly
against the same physical file with `CREATE ... IF NOT EXISTS` DDL, idempotent regardless of
which process runs it first. The correct long-term home for that DDL is
`core/persistence/db/schema.py` itself; this is recorded as a real, open item in this
package's own `CLAUDE.md` for whoever next touches Persistence's schema, at which point this
module's own provisioning call becomes a no-op safety net rather than the only place it runs.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from .fts_query import ensure_fts_schema

T = TypeVar("T")


def default_db_path(top_level: Path | str | None, user_id: str) -> Path:
    """The per-user canonical database path, matching
    `core/persistence/db/connection.py`'s own `default_db_path` exactly — see the module
    docstring for why this is re-derived rather than imported.
    """
    top = top_level if top_level is not None else os.environ.get("RESIBO_TOP_LEVEL")
    base = Path(top) if top else Path.home() / ".resibo"
    return base / "users" / user_id / "canonical.sqlite"


class ReceiptDatabaseRegistry:
    """Opens, caches, and schema-provisions one connection per user's canonical database.

    All query execution against a cached connection runs under this registry's own lock —
    `check_same_thread=False` only disables Python's own thread-affinity check, it does not
    make one SQLite connection safe for concurrent statement execution from multiple
    threads, so this is a real lock rather than a GIL assumption (`docs/PRINCIPLES.md`
    §3.3.1), the same discipline `core/groups/store.py` applies to its own single connection.

    A user with no canonical database yet is not a failure — it means they have never
    written a receipt, and a search over an empty result set is the correct answer
    (`docs/PRINCIPLES.md` §4.4). `run_sync`/`run` return `None` for that case; callers treat
    it as "no rows", never as an error.
    """

    def __init__(self, top_level: Path | str | None = None) -> None:
        self._top_level = top_level
        self._lock = threading.RLock()
        self._connections: dict[str, sqlite3.Connection] = {}
        self._fts_available: dict[str, bool] = {}

    def _get_locked(self, user_id: str) -> sqlite3.Connection | None:
        conn = self._connections.get(user_id)
        if conn is not None:
            return conn
        path = default_db_path(self._top_level, user_id)
        if not path.exists():
            return None
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        self._connections[user_id] = conn
        self._fts_available[user_id] = ensure_fts_schema(conn)
        return conn

    def fts_available(self, user_id: str) -> bool:
        """Whether `receipts_fts` is usable for this user right now.

        Only meaningful once `run`/`run_sync` has opened the connection at least once — a
        user with no database yet has no opinion either way, so this defaults to `False`
        rather than claiming availability it has not verified.
        """
        with self._lock:
            return self._fts_available.get(user_id, False)

    def run_sync(self, user_id: str, fn: Callable[[sqlite3.Connection], T]) -> T | None:
        """Run `fn` against `user_id`'s connection, or return `None` if they have no
        canonical database yet."""
        with self._lock:
            conn = self._get_locked(user_id)
            if conn is None:
                return None
            return fn(conn)

    async def run(self, user_id: str, fn: Callable[[sqlite3.Connection], T]) -> T | None:
        return await asyncio.to_thread(self.run_sync, user_id, fn)

    def close(self) -> None:
        with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()
            self._fts_available.clear()


async def in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run blocking work off the event loop — this API is async-wrapped blocking SQLite I/O
    the same way Auth, Audit, Logs, and Persistence itself already are (§5)."""
    return await asyncio.to_thread(fn, *args, **kwargs)


__all__ = ["ReceiptDatabaseRegistry", "default_db_path", "in_thread"]

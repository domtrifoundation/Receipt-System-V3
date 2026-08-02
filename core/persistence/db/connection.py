"""WAL-mode SQLite plus the async wrapper every caller in this package goes through (§3.1).

`sqlite3` is blocking by nature, so every call runs on an executor rather than on the event
loop. The executor is deliberately **single-threaded**: one connection, one thread, so
transactions serialize by construction instead of by a lock someone could forget to take.
WAL mode is what makes that acceptable — readers do not block writers and writers do not
block readers, at the cost of the WAL file's own small extra I/O.

**On the shared utility the deep-dive names.** §3.1 says this wrapper is worth exactly one
shared implementation (`common/async_sqlite.py`) rather than four — Auth's sessions, Audit's
events, Logs, and this API all need the identical shape. That extraction is correct and
should happen; it is not done here because `common/` is outside this package's own write
boundary while several APIs are being implemented in parallel. When it lands, this module
becomes a thin subclass that adds Persistence's own schema and PRAGMAs, and nothing outside
this file changes.

**Free-threading (`docs/PRINCIPLES.md` §3.3.1).** Nothing here assumes the GIL is
serializing anything. The single-worker executor is a real, explicit serialization boundary,
and it keeps meaning the same thing on a free-threaded build.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

from ..errors import DatabaseUnavailable
from .schema import CURRENT_SCHEMA_VERSION, SCHEMA

T = TypeVar("T")

#: `:memory:` databases are per-connection and have no WAL journal of their own. Tests use
#: them; production never does.
_MEMORY = ":memory:"


class Database:
    """Owns the connection. Nothing outside this class ever sees it.

    Handing out a raw connection is how an append-only guarantee gets bypassed by accident
    (`docs/PRINCIPLES.md` §2.3) — every caller gets a callable executed *against* the
    connection instead, so the surface stays enumerable.
    """

    def __init__(self, path: Path | str, *, schema: str = SCHEMA) -> None:
        self._path = str(path)
        if self._path != _MEMORY:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
        except sqlite3.Error as exc:  # pragma: no cover - environment-dependent
            raise DatabaseUnavailable(str(exc)) from exc
        self._conn.row_factory = sqlite3.Row
        # Explicit transaction control. With the default isolation level, sqlite3 opens and
        # commits transactions on its own schedule, which would quietly undo the whole
        # "these two writes share one transaction" guarantee §5 depends on.
        self._conn.isolation_level = None
        if self._path != _MEMORY:
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(schema)
        self._conn.execute(
            "INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(CURRENT_SCHEMA_VERSION),),
        )
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="persistence-db")

    @property
    def path(self) -> str:
        return self._path

    def close(self) -> None:
        self._executor.shutdown(wait=True)
        self._conn.close()

    # ------------------------------------------------------------------ sync
    def run_sync(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run `fn` against the connection with no transaction of its own.

        Present because Disaster Recovery and the CI-side tests genuinely run outside an
        event loop; the async path below is what service code uses.
        """
        return fn(self._conn)

    def transaction_sync(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run `fn` inside one `BEGIN IMMEDIATE`/`COMMIT`, rolling back on any exception.

        This is the mechanism behind Historian's entire reason for being a sub-package
        rather than a peer API: the canonical data write and its event insertion happen in
        one call to this method, so they commit together or not at all. `BEGIN IMMEDIATE`
        rather than a deferred begin — the write lock is taken up front so an interleaved
        writer cannot turn this into a busy-error partway through.
        """
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = fn(conn)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return result

    # ----------------------------------------------------------------- async
    async def run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.run_sync, fn)

    async def transaction(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.transaction_sync, fn)

    # ------------------------------------------------------------ snapshots
    def snapshot_to(self, destination: Path | str) -> Path:
        """Write a self-contained checkpoint of this database — Persistence's own recovery
        mechanism, and what Disaster Recovery restores from.

        Uses SQLite's own online-backup API rather than copying the file. **Copying a WAL
        database's `.sqlite` file alone silently produces a snapshot missing every committed
        transaction still living in the `-wal` file** — it opens without error and simply has
        no recent data in it, which is the worst possible shape for a backup to fail in. The
        backup API checkpoints properly and is safe against concurrent writers.
        """
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(target)) as backup_conn:
            self._conn.backup(backup_conn)
        return target

    # ----------------------------------------------------------------- meta
    def schema_version(self) -> int:
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        return int(row["value"]) if row else CURRENT_SCHEMA_VERSION


def default_db_path(top_level: Path | str | None, user_id: str) -> Path:
    """The per-user database path.

    Per-user data lives in the top-level installation directory, a sibling of every release
    clone, never inside the repository (`docs/PRINCIPLES.md` §1.6, §2.4). The per-user
    *folder* boundary is itself the isolation mechanism (§4.5) — a structural guarantee
    rather than a permission check, so a role-check bug elsewhere cannot reach another
    user's rows.
    """
    base = Path(top_level) if top_level else Path.home() / ".resibo"
    return base / "users" / user_id / "canonical.sqlite"


def default_blob_root(top_level: Path | str | None, user_id: str) -> Path:
    """The per-user blob store root, same placement reasoning as `default_db_path`."""
    base = Path(top_level) if top_level else Path.home() / ".resibo"
    return base / "users" / user_id / "blobs"


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """`sqlite3.Row` is not a mapping the rest of this package wants to pass around."""
    return [dict(row) for row in rows]


__all__ = [
    "Database",
    "default_blob_root",
    "default_db_path",
    "rows_to_dicts",
]

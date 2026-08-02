"""The query-acceleration index (§3.2) — a SQLite table over the JSONL files.

**This is not a second source of truth and must never become one.** It stores where an entry
is (`path`, byte `offset`, `length`) plus the fields a query filters on, and never the log
content itself. Two consequences that are load-bearing rather than stylistic:

- It is **fully rebuildable from the JSONL files alone** (`rebuild()`), and there is a test
  that deletes the database and regenerates it precisely to keep that claim honest.
- Losing it or failing to open it is **not an error for the caller**. `query.py` catches
  `IndexUnavailable` and answers by scanning the files instead — slower, identical answer.

This table is deliberately not routed through Persistence's Historian (§1) and is not
"typed, learned, or schema data" in `docs/PRINCIPLES.md` §3.4's sense, so it is not an
Architect concern: it holds no taxonomy and nothing learned, only byte offsets into files
this API already owns. Deleting it costs a rebuild and nothing else.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .contracts import IndexRebuildResult, LogEntry, LogQuery, WriteReceipt
from .contracts import LEVEL_SEVERITY, utc_iso
from .errors import IndexUnavailable
from .jsonl import decode
from .paths import default_log_root, iter_log_files

_SCHEMA = """
CREATE TABLE IF NOT EXISTS log_index (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    path     TEXT    NOT NULL,
    offset   INTEGER NOT NULL,
    length   INTEGER NOT NULL,
    ts       TEXT    NOT NULL,
    service  TEXT    NOT NULL,
    level    TEXT    NOT NULL,
    severity INTEGER NOT NULL,
    run_id   TEXT,
    user_id  TEXT,
    UNIQUE (path, offset)
);
CREATE INDEX IF NOT EXISTS idx_log_run  ON log_index(run_id, ts);
CREATE INDEX IF NOT EXISTS idx_log_user ON log_index(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_log_svc  ON log_index(service, ts);
"""


def default_index_path() -> Path:
    """Beside the logs it indexes, in the top-level installation directory — never inside
    the repository or a release clone (`docs/PRINCIPLES.md` §1.6)."""
    return default_log_root() / "index.sqlite"


class LogIndex:
    """Owns its connection. Nothing outside this class sees it."""

    def __init__(self, db_path: Path | str | None = None, *, root: Path | None = None) -> None:
        self._path = Path(db_path) if db_path else default_index_path()
        self._root = Path(root) if root else default_log_root()
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._open()

    # ----------------------------------------------------------------- lifecycle
    def _open(self) -> None:
        try:
            if str(self._path) != ":memory:":
                self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            if str(self._path) != ":memory:":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        except (sqlite3.Error, OSError) as exc:
            # Degraded, not fatal: the files are the real data and remain fully queryable.
            self._conn = None
            self._unavailable = str(exc)
            return
        self._conn = conn
        self._unavailable = ""

    @property
    def available(self) -> bool:
        return self._conn is not None

    def _require(self) -> sqlite3.Connection:
        if self._conn is None:
            raise IndexUnavailable(self._unavailable or f"{self._path} is not usable")
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ----------------------------------------------------------------- write path
    def record(self, entry: LogEntry, receipt: WriteReceipt) -> bool:
        """Point at one just-written entry. Returns False if the index is unusable.

        Never raises at the caller: an index that cannot be written is a slower query later,
        not a failed log write now.
        """
        if not receipt.written or not receipt.path:
            return False
        try:
            conn = self._require()
            with self._lock:
                conn.execute(
                    "INSERT OR IGNORE INTO log_index"
                    " (path, offset, length, ts, service, level, severity, run_id, user_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        receipt.path, receipt.offset, receipt.length,
                        utc_iso(entry.timestamp), entry.service, entry.level.value,
                        LEVEL_SEVERITY[entry.level], entry.run_id, entry.user_id,
                    ),
                )
                conn.commit()
        except (IndexUnavailable, sqlite3.Error):
            return False
        return True

    # ----------------------------------------------------------------- read path
    def locate(self, query: LogQuery) -> tuple[tuple[str, int, int], ...]:
        """`(path, offset, length)` for every entry matching the query, oldest first.

        Raises `IndexUnavailable` when there is no usable index — the caller is expected to
        fall back to scanning, which is what keeps this class an accelerator rather than a
        dependency.
        """
        conn = self._require()
        sql = ["SELECT path, offset, length FROM log_index WHERE severity >= ?"]
        params: list = [LEVEL_SEVERITY[query.min_level]]
        if query.run_id:
            sql.append("AND run_id = ?")
            params.append(query.run_id)
        if query.user_id:
            sql.append("AND user_id = ?")
            params.append(query.user_id)
        if query.service:
            sql.append("AND service = ?")
            params.append(query.service)
        # `ts` is compared as text, so both sides have to be in the one offset every row
        # was stored with. A caller's `+08:00` bound compared raw against a `+00:00` column
        # is a lexicographic comparison that is not a chronological one, and the answer
        # would then differ from the scan path's — see `contracts.as_utc`.
        if query.since:
            sql.append("AND ts >= ?")
            params.append(utc_iso(query.since))
        if query.until:
            sql.append("AND ts <= ?")
            params.append(utc_iso(query.until))
        # One past the limit, so the caller can report truncation honestly instead of
        # silently handing back a clipped answer that looks complete.
        sql.append("ORDER BY ts ASC, id ASC LIMIT ?")
        params.append(max(int(query.limit), 0) + 1)
        try:
            with self._lock:
                rows = conn.execute(" ".join(sql), params).fetchall()
        except sqlite3.Error as exc:
            raise IndexUnavailable(str(exc)) from exc
        return tuple((r["path"], r["offset"], r["length"]) for r in rows)

    # ----------------------------------------------------------------- maintenance
    def rebuild(self, root: Path | None = None) -> IndexRebuildResult:
        """Regenerate the whole index from the JSONL files alone (§3.2's design claim).

        Reads each file in binary and tracks byte offsets directly rather than trusting the
        text layer's own idea of position — a text-mode `tell()` on Windows is not a byte
        count, and an index whose offsets are wrong is worse than no index at all.
        """
        root = Path(root) if root else self._root
        try:
            conn = self._require()
        except IndexUnavailable as exc:
            return IndexRebuildResult(error_code="INDEX_UNAVAILABLE", error_detail=str(exc))

        files = 0
        indexed = 0
        try:
            with self._lock:
                conn.execute("DELETE FROM log_index")
                for path in iter_log_files(root):
                    files += 1
                    indexed += self._ingest_file(conn, path)
                conn.commit()
        except (sqlite3.Error, OSError) as exc:
            return IndexRebuildResult(
                files_scanned=files, error_code="REBUILD_FAILED", error_detail=str(exc)
            )
        return IndexRebuildResult(files_scanned=files, entries_indexed=indexed)

    @staticmethod
    def _ingest_file(conn: sqlite3.Connection, path: Path) -> int:
        indexed = 0
        offset = 0
        with open(path, "rb") as handle:
            for raw in handle:
                length = len(raw)
                entry = decode(raw)
                offset_of_line, offset = offset, offset + length
                if entry is None:
                    continue  # truncated or unreadable line — skipped, never fatal
                conn.execute(
                    "INSERT OR IGNORE INTO log_index"
                    " (path, offset, length, ts, service, level, severity, run_id, user_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        str(path), offset_of_line, length, utc_iso(entry.timestamp),
                        entry.service, entry.level.value, LEVEL_SEVERITY[entry.level],
                        entry.run_id, entry.user_id,
                    ),
                )
                indexed += 1
        return indexed

    def prune_paths(self, paths: tuple[str, ...] | list[str]) -> int:
        """Drop rows pointing at files retention has deleted. Returns rows removed."""
        if not paths:
            return 0
        try:
            conn = self._require()
            with self._lock:
                cur = conn.execute(
                    f"DELETE FROM log_index WHERE path IN ({','.join('?' * len(paths))})",
                    tuple(str(p) for p in paths),
                )
                conn.commit()
        except (IndexUnavailable, sqlite3.Error):
            return 0
        return cur.rowcount or 0

    def count(self) -> int:
        try:
            conn = self._require()
            with self._lock:
                return int(conn.execute("SELECT COUNT(*) AS n FROM log_index").fetchone()["n"])
        except (IndexUnavailable, sqlite3.Error):
            return 0


__all__ = ["LogIndex", "default_index_path"]

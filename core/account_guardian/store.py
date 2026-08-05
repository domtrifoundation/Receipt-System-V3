"""Account Guardian's own top-level SQLite database.

**Not in the deep-dive's §2 package layout.** The deep-dive's own sketches (`request_export`,
`request_deletion`, §5's recovery case queue) all imply durable state that survives a process
restart — a deletion request's grace period has to still be there tomorrow, and Background
Workers' own sweep (deep-dive §6.3) needs something to query — but §2 never names where that
state lives. This module is that answer, and it is added with the same reasoning
`core/auth/store.py` already gives for its own placement (deep-dive-05 §5.2):

**Recovery requests, SSO-link requests, export requests, deletion requests, and consent
records are all cross-user, cross-session infrastructure, not any one user's Persistence
data.** A user filing a recovery request has, by definition, lost the authentication method
that would normally resolve which per-user Persistence folder is theirs — this state cannot
live inside the very per-user store the user may not be able to reach. So it lives in its own
small database at the top level, alongside Auth's and Audit's (`docs/PRINCIPLES.md` §1.6),
outside every release clone, with its own deliberately non-overlapping scope.

**This is not a §3.4 violation.** Architect API owns typed/learned/schema data — taxonomies,
vendor directories, anything the system *teaches* itself. Nothing here is that: every table
below is transactional request/case state, the same shape Auth's own `DeletionStage`-style
sketch already put directly in `contracts.py` rather than routing through Architect.

Every method here is synchronous; the async surfaces in `devices.py`, `account_recovery.py`,
`sso_linking.py`, `privacy/*.py` and `consent.py` reach it through `in_thread`, the identical
one-helper-per-package convention `core/auth/store.py` uses, so there is exactly one place
"this touches disk, get it off the event loop" is expressed.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recovery_requests (
    request_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    lost_method  TEXT,
    requested_at TEXT NOT NULL,
    stage        TEXT NOT NULL,
    checklist_json TEXT NOT NULL DEFAULT '{}',
    reviewed_by  TEXT,
    resolved_at  TEXT,
    notes        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_recovery_user ON recovery_requests(user_id);

CREATE TABLE IF NOT EXISTS sso_link_requests (
    request_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    provider     TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    stage        TEXT NOT NULL,
    completed_at TEXT,
    error_detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sso_link_user ON sso_link_requests(user_id);

CREATE TABLE IF NOT EXISTS export_requests (
    request_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    status       TEXT NOT NULL,
    export_logical_id TEXT,
    error_detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_export_user ON export_requests(user_id);

CREATE TABLE IF NOT EXISTS deletion_requests (
    request_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    stage        TEXT NOT NULL,
    grace_period_ends_at TEXT,
    completed_at TEXT
);
-- At most one *active* (non-terminal) deletion lifecycle per user, enforced structurally
-- rather than by caller discipline — a partial unique index rather than a UNIQUE column,
-- because a user is allowed to file, cancel, and later file again.
CREATE UNIQUE INDEX IF NOT EXISTS idx_deletion_active_user ON deletion_requests(user_id)
    WHERE stage NOT IN ('complete', 'cancelled');
CREATE INDEX IF NOT EXISTS idx_deletion_stage ON deletion_requests(stage);

CREATE TABLE IF NOT EXISTS consent_records (
    user_id          TEXT NOT NULL,
    document_type    TEXT NOT NULL,
    document_version TEXT NOT NULL,
    accepted_at      TEXT NOT NULL,
    ip_address       TEXT,
    PRIMARY KEY (user_id, document_type, document_version)
);

CREATE TABLE IF NOT EXISTS policy_versions (
    document_type      TEXT NOT NULL,
    version             TEXT NOT NULL,
    requires_reconsent  INTEGER NOT NULL DEFAULT 0,
    published_at        TEXT NOT NULL,
    text_ref             TEXT NOT NULL DEFAULT '',
    is_current            INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (document_type, version)
);
-- Exactly one "current" version per document type, enforced the same structural way as the
-- active-deletion constraint above rather than trusted to application discipline.
CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_current ON policy_versions(document_type)
    WHERE is_current = 1;
"""


def default_db_path() -> Path:
    """Top-level installation directory, never inside a release clone (§1.6).

    Identical resolution to `core/auth/store.py.default_db_path` — `RESIBO_TOP_LEVEL` is how
    Supervisor tells a service where the shared top level is; the fallback keeps a bare
    developer checkout runnable without pretending the repo itself is the right home for
    cross-user request state.
    """
    top = os.environ.get("RESIBO_TOP_LEVEL")
    base = Path(top) if top else Path.home() / ".resibo"
    return base / "account_guardian.sqlite"


async def in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run blocking SQLite work off the event loop. One helper, not a scattered
    `asyncio.to_thread` at every call site (deep-dive §8.1: this API is I/O-bound with no
    compute-bound work of its own)."""
    return await asyncio.to_thread(fn, *args, **kwargs)


class AccountGuardianDatabase:
    """Owns the one connection to this package's database. Nothing outside this file sees
    the raw connection — every sibling module goes through `write`/`query_one`/`query_all`,
    the same guarded-primitive shape `core/auth/store.py.AuthDatabase` uses."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else default_db_path()
        memory = str(self._path) == ":memory:"
        if not memory:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if not memory:
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def write(self, sql: str, params: tuple | list = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.rowcount

    def query_one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def query_all(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()


__all__ = ["AccountGuardianDatabase", "default_db_path", "in_thread"]

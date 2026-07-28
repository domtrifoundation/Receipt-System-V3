"""SQLite persistence for agent tokens, the agent audit trail, and rate-limit counters.

**Why this file exists at all, stated plainly rather than left to look like a shortcut**:
`docs/PRINCIPLES.md` §2.4 and Persistence API's own boundary say nothing but Persistence
touches disk. Persistence does not exist yet — Phase 1 scaffolds it and Phase 2 implements
it. Agent Control is the one API implemented ahead of that, so it needs somewhere real to
put tokens now.

The resolution is deliberate and narrow: this store owns *only* Agent Control's own
operational state (tokens, agent audit entries, rate counters), never receipt or user
business data, and it lives in the top-level installation directory rather than inside the
repository (§1.6). When Persistence and Audit exist, `AgentAuditSink` moves to Audit API's
own append-only log and this file keeps only the token table — a bounded, known migration,
not an open-ended parallel datastore.

The audit table is append-only structurally, not by convention (§2.3): there is no update
or delete method on this class, and nothing here hands out the raw connection.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.frozen_dict import FrozenDict

from .contracts import AgentAction, AgentToken, ToolCategory, utcnow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_tokens (
    token_id        TEXT PRIMARY KEY,
    token_hash      TEXT NOT NULL UNIQUE,
    issued_by       TEXT NOT NULL,
    issued_to_label TEXT NOT NULL,
    scopes          TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('client', 'staff')),
    issued_at       TEXT NOT NULL,
    expires_at      TEXT,
    revoked_at      TEXT
);

-- Append-only. No UPDATE or DELETE path exists in this module for this table.
CREATE TABLE IF NOT EXISTS agent_audit (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id   TEXT NOT NULL,
    tool_name  TEXT NOT NULL,
    category   TEXT NOT NULL,
    arguments  TEXT NOT NULL,
    at         TEXT NOT NULL,
    outcome    TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agent_audit_token ON agent_audit(token_id, at);
"""

#: The role CHECK constraint above is the database-level half of §3.1's owner ceiling. The
#: application-level half is in `token_lifecycle.issue_token`. Both exist on purpose: a
#: structural guarantee is preferred over a check-based one wherever both are available
#: (`docs/PRINCIPLES.md` §4.5), and here both genuinely are.


def default_db_path() -> Path:
    """Top-level installation directory, never inside a release clone (§1.6).

    `RESIBO_TOP_LEVEL` is how Supervisor tells a service where the shared top level is. The
    fallback keeps a bare developer checkout runnable without pretending the repo is the
    right home for it — it resolves outside the repo, not into `data/`.
    """
    top = os.environ.get("RESIBO_TOP_LEVEL")
    base = Path(top) if top else Path.home() / ".resibo"
    return base / "agent_control.sqlite"


class AgentStore:
    """Owns the connection. Nothing outside this class sees it."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else default_db_path()
        if str(self._path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL for safe concurrent access, matching Persistence's own stated mode.
        if str(self._path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- tokens
    def insert_token(self, token: AgentToken, token_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_tokens (token_id, token_hash, issued_by, issued_to_label,"
                " scopes, role, issued_at, expires_at, revoked_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    token.token_id, token_hash, token.issued_by, token.issued_to_label,
                    json.dumps(list(token.scopes)), token.role,
                    token.issued_at.isoformat(),
                    token.expires_at.isoformat() if token.expires_at else None,
                    token.revoked_at.isoformat() if token.revoked_at else None,
                ),
            )
            self._conn.commit()

    @staticmethod
    def _row_to_token(row: sqlite3.Row) -> AgentToken:
        def dt(v: str | None) -> datetime | None:
            return datetime.fromisoformat(v) if v else None

        return AgentToken(
            token_id=row["token_id"],
            issued_by=row["issued_by"],
            issued_to_label=row["issued_to_label"],
            scopes=tuple(json.loads(row["scopes"])),
            role=row["role"],
            issued_at=dt(row["issued_at"]),  # type: ignore[arg-type]
            expires_at=dt(row["expires_at"]),
            revoked_at=dt(row["revoked_at"]),
        )

    def find_by_hash(self, token_hash: str) -> AgentToken | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agent_tokens WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        return self._row_to_token(row) if row else None

    def find_by_id(self, token_id: str) -> AgentToken | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agent_tokens WHERE token_id = ?", (token_id,)
            ).fetchone()
        return self._row_to_token(row) if row else None

    def list_tokens(self, include_inactive: bool = True) -> list[AgentToken]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_tokens ORDER BY issued_at DESC"
            ).fetchall()
        tokens = [self._row_to_token(r) for r in rows]
        return tokens if include_inactive else [t for t in tokens if t.is_active()]

    def revoke(self, token_id: str, when: datetime | None = None) -> datetime | None:
        """Revocation is a single committed UPDATE — it takes effect on the next
        authentication, never on a cache-expiry delay (deep-dive §10's own test)."""
        when = when or utcnow()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE agent_tokens SET revoked_at = ? WHERE token_id = ? AND revoked_at IS NULL",
                (when.isoformat(), token_id),
            )
            self._conn.commit()
        return when if cur.rowcount else None

    # ---------------------------------------------------------------- audit
    def append_audit(self, action: AgentAction) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_audit (token_id, tool_name, category, arguments, at,"
                " outcome, detail) VALUES (?,?,?,?,?,?,?)",
                (
                    action.token_id, action.tool_name, action.category.value,
                    json.dumps(dict(action.arguments), default=str),
                    action.at.isoformat(), action.outcome, action.detail,
                ),
            )
            self._conn.commit()

    def read_audit(self, token_id: str | None = None, limit: int = 100) -> list[AgentAction]:
        sql = "SELECT * FROM agent_audit"
        params: tuple = ()
        if token_id:
            sql += " WHERE token_id = ?"
            params = (token_id,)
        sql += " ORDER BY seq DESC LIMIT ?"
        params += (limit,)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            AgentAction(
                token_id=r["token_id"], tool_name=r["tool_name"],
                category=ToolCategory(r["category"]),
                arguments=FrozenDict(json.loads(r["arguments"])),
                at=datetime.fromisoformat(r["at"]),
                outcome=r["outcome"], detail=r["detail"],
            )
            for r in rows
        ]

    def count_actions_since(
        self, token_id: str, since: datetime, categories: tuple[ToolCategory, ...] | None = None
    ) -> int:
        """Counts *attempts*, from the same append-only audit trail the actions are recorded
        in — deliberately one source of truth rather than a separate in-memory counter that
        could disagree with the audit log about what happened."""
        sql = "SELECT COUNT(*) AS n FROM agent_audit WHERE token_id = ? AND at >= ?"
        params: list = [token_id, since.isoformat()]
        if categories:
            sql += f" AND category IN ({','.join('?' * len(categories))})"
            params += [c.value for c in categories]
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return int(row["n"])


__all__ = ["AgentStore", "default_db_path", "timedelta", "timezone"]

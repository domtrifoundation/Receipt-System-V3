"""The one place `sqlite3` is imported in this package — schema, connection, raw CRUD.

**Why this file exists when the deep-dive's §3 layout does not list it**: the layout names
`membership.py` as owning "create/add/remove/manager-toggle", but that is the *orchestration*
— validation, the audit hook, the fail-closed permission call — and putting raw SQL in the
same file as that would mean `permission_gate.py` and `effective_group.py` each duplicating
their own row-mapping to read membership state, three places the same query could drift
apart. One adapter, imported by all three, is the same shape `core/audit/db.py` and
`core/logs/paths.py` already use for exactly this reason. This also satisfies
`docs/PRINCIPLES.md` §1.3 at library granularity: `sqlite3` is an external library, so it
sits behind one small internal adapter rather than being imported at scattered call sites.

**This is the same physical database file Auth's own `AuthDatabase` opens** (deep-dive §3):
Groups is identity/org-structure data, the same category as users/sessions/break-glass
grants, and does not get a fourth top-level database of its own
(`docs/PRINCIPLES.md` §1.6). `default_db_path()` below is *re-derived* here rather than
imported from `core.auth.store` — `contracts.py` is the only module another package may
import from (`docs/PRINCIPLES.md` §1.1), and `core.auth.store` is Auth's own internal file,
not its published contract. Multiple independent connections to one SQLite file under WAL
mode is exactly the mechanism Persistence and Audit already rely on elsewhere in this
project; Groups' own tables (`groups`, `group_memberships`, `group_active_selection`) are
additive to that same file and never touch Auth's own tables.

Groups' own tables are genuinely mutable — a membership is added, removed, and its
`is_group_manager` flag flips — so, unlike Audit's connection, there is no append-only
authorizer here. Structural append-only enforcement belongs to Audit and Historian
specifically (`docs/PRINCIPLES.md` §2.3); a team roster is ordinary CRUD.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import Group, GroupMembership

_SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    group_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_memberships (
    group_id         TEXT NOT NULL,
    user_id          TEXT NOT NULL,
    is_group_manager INTEGER NOT NULL DEFAULT 0,
    joined_at        TEXT NOT NULL,
    added_by         TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_memberships_user ON group_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_group ON group_memberships(group_id);

-- §5/§11: the user's own explicitly-set "active group", defaulted to whichever group they
-- most recently joined until they (or `effective_group.py`'s own bootstrap) set it
-- explicitly. One row per user — a user with no row has never had an effective group
-- resolved for them at all.
CREATE TABLE IF NOT EXISTS group_active_selection (
    user_id  TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    set_at   TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    """Auth's own top-level database file (deep-dive §3). See the module docstring for why
    this is re-derived rather than imported."""
    top = os.environ.get("RESIBO_TOP_LEVEL")
    base = Path(top) if top else Path.home() / ".resibo"
    return base / "auth.sqlite"


async def in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run blocking SQLite work off the event loop — the one place this package expresses
    "this touches disk, get it off the loop" (`membership.py` and `effective_group.py` both
    use this rather than each opening its own `asyncio.to_thread` call, the same reasoning
    `core/auth/store.py`'s own `in_thread` states in full)."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_group(row: sqlite3.Row) -> Group:
    return Group(
        group_id=row["group_id"], name=row["name"], created_by=row["created_by"],
        created_at=_dt(row["created_at"]),
    )


def _row_to_membership(row: sqlite3.Row) -> GroupMembership:
    return GroupMembership(
        group_id=row["group_id"], user_id=row["user_id"],
        is_group_manager=bool(row["is_group_manager"]),
        joined_at=_dt(row["joined_at"]), added_by=row["added_by"],
    )


class GroupsStore:
    """Owns the one connection this package uses. Nothing outside this file sees it."""

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
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ groups
    def insert_group(self, group: Group) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO groups (group_id, name, created_by, created_at)"
                " VALUES (?,?,?,?)",
                (group.group_id, group.name, group.created_by, group.created_at.isoformat()),
            )
            self._conn.commit()

    def get_group(self, group_id: str) -> Group | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM groups WHERE group_id = ?", (group_id,)
            ).fetchone()
        return _row_to_group(row) if row else None

    # ------------------------------------------------------------ memberships
    def insert_membership(self, membership: GroupMembership) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO group_memberships (group_id, user_id, is_group_manager,"
                " joined_at, added_by) VALUES (?,?,?,?,?)",
                (membership.group_id, membership.user_id, int(membership.is_group_manager),
                 membership.joined_at.isoformat(), membership.added_by),
            )
            self._conn.commit()

    def get_membership(self, group_id: str, user_id: str) -> GroupMembership | None:
        """A **live** read against current state — never cached, and no expiry timer to
        reason about (deep-dive §7's "persistent and structural doesn't mean never re-checked"
        distinction). Every caller of this, including `permission_gate.py`, hits this query
        again on every call rather than remembering a prior answer."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM group_memberships WHERE group_id = ? AND user_id = ?",
                (group_id, user_id),
            ).fetchone()
        return _row_to_membership(row) if row else None

    def delete_membership(self, group_id: str, user_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM group_memberships WHERE group_id = ? AND user_id = ?",
                (group_id, user_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def set_manager_flag(self, group_id: str, user_id: str, is_manager: bool) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE group_memberships SET is_group_manager = ?"
                " WHERE group_id = ? AND user_id = ?",
                (int(is_manager), group_id, user_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list_memberships_for_group(self, group_id: str) -> list[GroupMembership]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM group_memberships WHERE group_id = ? ORDER BY joined_at",
                (group_id,),
            ).fetchall()
        return [_row_to_membership(r) for r in rows]

    def list_memberships_for_user(self, user_id: str) -> list[GroupMembership]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM group_memberships WHERE user_id = ? ORDER BY joined_at DESC",
                (user_id,),
            ).fetchall()
        return [_row_to_membership(r) for r in rows]

    # -------------------------------------------------------- active selection
    def get_active_group(self, user_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT group_id FROM group_active_selection WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["group_id"] if row else None

    def set_active_group(self, user_id: str, group_id: str, set_at: datetime) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO group_active_selection (user_id, group_id, set_at) VALUES (?,?,?)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                " group_id = excluded.group_id, set_at = excluded.set_at",
                (user_id, group_id, set_at.isoformat()),
            )
            self._conn.commit()

    def clear_active_group_if(self, user_id: str, group_id: str) -> None:
        """Called when a membership is removed: an active selection pointing at a group the
        user no longer belongs to must not silently keep resolving (deep-dive §7's live
        re-check discipline, applied to the selector rather than only to reads)."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM group_active_selection WHERE user_id = ? AND group_id = ?",
                (user_id, group_id),
            )
            self._conn.commit()


__all__ = ["GroupsStore", "default_db_path", "in_thread"]

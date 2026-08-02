"""Server-side session persistence (deep-dive §5.1–§5.3).

Sessions are server-side rows, not JWTs handed to the browser, for one concrete reason:
owner/staff access sometimes has to be pulled *instantly*. Revocation here is a single
committed row update, visible on the very next request — no expiry window to wait out, no
blocklist to distribute, no cache to invalidate. A stateless JWT plus a blocklist is a
server-side session store wearing a costume, and it still has to solve invalidation
correctly on top.

**The API is async and the storage is not.** Every method hops to a thread via
`store.in_thread` rather than blocking the loop on a SQLite syscall. That is this API's
concurrency bucket in full: I/O-bound throughout, no compute-bound pure-Python hot path
(deep-dive §8.1–§8.2).

**Two shapes on purpose**: `get()` returns `Session | None` for callers that legitimately
branch on absence; `validate()` raises. `validate()` is what the gRPC surface calls, because
a caller silently ignoring an expired session is exactly the failure `docs/PRINCIPLES.md`
§4.1 carves this API out for.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta

from ..contracts import IssuedSession, Role, Session, utcnow
from ..errors import SessionExpired, SessionInvalid
from ..store import AuthDatabase, in_thread

#: `ValidateSession` runs on effectively every authenticated request in the system, so this
#: statement is the one whose plan matters. `session_id` is the PRIMARY KEY, which SQLite
#: serves from the table's own rowid index — a single indexed read, never a scan. The §11
#: testing hook asserts exactly this against `EXPLAIN QUERY PLAN` rather than inferring it
#: from a timing run.
_LOOKUP_SQL = "SELECT * FROM sessions WHERE session_id = ?"


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        session_id=row["session_id"],
        user_id=row["user_id"],
        role=Role(row["role"]),
        created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
        last_seen_at=_dt(row["last_seen_at"]),  # type: ignore[arg-type]
        expires_at=_dt(row["expires_at"]),  # type: ignore[arg-type]
        revoked_at=_dt(row["revoked_at"]),
        step_up_at=_dt(row["step_up_at"]),
    )


class SessionStore:
    def __init__(self, db: AuthDatabase, ttl_hours: int = 720) -> None:
        self._db = db
        self._ttl = timedelta(hours=ttl_hours)

    # ------------------------------------------------------------- sync core
    # The synchronous methods are the real implementation; the async ones below are the
    # public surface. Keeping both rather than only the async form means the background
    # sweep and the tests can call this without an event loop, and there is still exactly
    # one place the SQL lives.
    def create_sync(self, user_id: str, role: Role) -> IssuedSession:
        now = utcnow()
        session = Session(
            # 256 bits from the OS CSPRNG. Opaque and never derived from `user_id` or any
            # other guessable value — deep-dive §3 states this as a property of the type.
            session_id=secrets.token_urlsafe(32),
            user_id=user_id,
            # Snapshotted here, not joined live (§5.3). See `roles/role_check.py` for the
            # obligation that creates on every role change.
            role=role,
            created_at=now,
            last_seen_at=now,
            expires_at=now + self._ttl,
        )
        csrf_token = secrets.token_urlsafe(32)
        self._db.write(
            "INSERT INTO sessions (session_id, user_id, role, csrf_token, created_at,"
            " last_seen_at, expires_at, revoked_at, step_up_at)"
            " VALUES (?,?,?,?,?,?,?,NULL,NULL)",
            (session.session_id, user_id, role.value, csrf_token, now.isoformat(),
             now.isoformat(), session.expires_at.isoformat()),
        )
        return IssuedSession(session=session, csrf_token=csrf_token)

    def get_sync(self, session_id: str) -> Session | None:
        row = self._db.query_one(_LOOKUP_SQL, (session_id,))
        return _row_to_session(row) if row else None

    def csrf_token_sync(self, session_id: str) -> str | None:
        row = self._db.query_one(
            "SELECT csrf_token FROM sessions WHERE session_id = ?", (session_id,)
        )
        return row["csrf_token"] if row else None

    def validate_sync(self, session_id: str) -> Session:
        session = self.get_sync(session_id)
        if session is None or session.revoked_at is not None:
            raise SessionInvalid(f"no active session {session_id[:8]}…")
        if session.expires_at <= utcnow():
            raise SessionExpired(f"session {session_id[:8]}… expired at {session.expires_at}")
        return session

    def touch_sync(self, session_id: str) -> None:
        self._db.write(
            "UPDATE sessions SET last_seen_at = ? WHERE session_id = ? AND revoked_at IS NULL",
            (utcnow().isoformat(), session_id),
        )

    def revoke_sync(self, session_id: str) -> bool:
        return self._db.write(
            "UPDATE sessions SET revoked_at = ?"
            " WHERE session_id = ? AND revoked_at IS NULL",
            (utcnow().isoformat(), session_id),
        ) == 1

    def revoke_all_for_user_sync(self, user_id: str) -> int:
        """The "log out everywhere" path — and the mandatory half of every role change.

        Returns how many sessions were actually revoked so a caller can log it; the count
        is information, never a condition to branch on (zero is a perfectly ordinary
        outcome for a user with no live sessions).
        """
        return self._db.write(
            "UPDATE sessions SET revoked_at = ?"
            " WHERE user_id = ? AND revoked_at IS NULL",
            (utcnow().isoformat(), user_id),
        )

    def mark_step_up_sync(self, session_id: str, when: datetime | None = None) -> None:
        """Record that §4.5's step-up re-authentication was satisfied on this session."""
        self._db.write(
            "UPDATE sessions SET step_up_at = ?"
            " WHERE session_id = ? AND revoked_at IS NULL",
            ((when or utcnow()).isoformat(), session_id),
        )

    def purge_expired_sync(self, older_than: datetime | None = None) -> int:
        """Cleanliness only — a Background Workers job (deep-dive §6.3). `validate_sync`
        never depends on it having run, so a missed sweep cannot extend a session's life."""
        return self._db.write(
            "DELETE FROM sessions WHERE expires_at <= ?",
            ((older_than or utcnow()).isoformat(),),
        )

    def lookup_plan(self, session_id: str = "x") -> list[str]:
        """Query plan for the hot path, for the §11 index assertion."""
        return self._db.explain(_LOOKUP_SQL, (session_id,))

    # ---------------------------------------------------------- async surface
    async def create(self, user_id: str, role: Role) -> IssuedSession:
        """Deep-dive §5.2 sketches this as `-> Session`; it returns `IssuedSession` because
        §5.4's CSRF synchronizer token has to be issued in the same act as the cookie, and
        a second call to fetch it would be a second chance to forget."""
        return await in_thread(self.create_sync, user_id, role)

    async def get(self, session_id: str) -> Session | None:
        return await in_thread(self.get_sync, session_id)

    async def validate(self, session_id: str) -> Session:
        return await in_thread(self.validate_sync, session_id)

    async def touch(self, session_id: str) -> None:
        await in_thread(self.touch_sync, session_id)

    async def revoke(self, session_id: str) -> bool:
        return await in_thread(self.revoke_sync, session_id)

    async def revoke_all_for_user(self, user_id: str) -> int:
        return await in_thread(self.revoke_all_for_user_sync, user_id)

    async def mark_step_up(self, session_id: str) -> None:
        await in_thread(self.mark_step_up_sync, session_id)

    async def csrf_token(self, session_id: str) -> str | None:
        return await in_thread(self.csrf_token_sync, session_id)


__all__ = ["SessionStore"]

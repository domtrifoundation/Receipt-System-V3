"""Auth's own top-level SQLite database — connection, schema, and the user directory.

**Placement, which is a real architectural decision and not a default** (deep-dive §5.2):
sessions and user accounts are cross-user infrastructure. They cannot live inside a
per-user Persistence folder, because "which user is this" is the question a session answers
*before* any per-user folder is even known. So Auth owns one small, separate database in the
top-level installation directory alongside config and models (`docs/PRINCIPLES.md` §1.6) —
outside every release clone, and distinct from both any user's canonical Persistence
database and Architect's global moderation-queue database. Three databases, three
deliberately non-overlapping scopes.

**This is not a §3.4 violation.** Architect API owns typed/learned/schema data — taxonomies,
vendor directories, anything a user or the system *teaches* the program. Nothing here is
that. These are identity and session mechanics, which the deep-dive assigns to this API
explicitly.

**Everything in this module is synchronous** and the connection never leaves this file. The
async surfaces the deep-dive specifies (`SessionStore`, `AuthMethodProvider`) reach it
through `in_thread()`, one helper, so there is a single place where "this touches disk, get
it off the event loop" is expressed rather than an `asyncio.to_thread` at every call site.

There is no password column, no password hash column, and no table that could hold one.
That is the schema-level half of deep-dive §4's "no local passwords, ever" — a structural
guarantee rather than a review convention (`docs/PRINCIPLES.md` §4.5).
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

from .contracts import PasskeyCredential, Role, TwoFactorConfig, User, utcnow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      TEXT PRIMARY KEY,
    role         TEXT NOT NULL CHECK (role IN ('owner', 'staff', 'client')),
    email        TEXT NOT NULL,
    phone_number TEXT,
    sso_provider TEXT,
    sso_subject  TEXT,
    created_at   TEXT NOT NULL
);
-- The IdP subject is the identity key, not the email (deep-dive §4.2). The uniqueness
-- constraint is on (provider, subject) for exactly that reason: an email is allowed to
-- change on the IdP side and be re-synced here without becoming a different user.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_sso
    ON users(sso_provider, sso_subject) WHERE sso_subject IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('owner', 'staff', 'client')),
    csrf_token   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    revoked_at   TEXT,
    step_up_at   TEXT
);
-- ValidateSession is the highest-volume call in the whole system (deep-dive §9), so its
-- lookup is the PRIMARY KEY index and nothing else. This second index exists only for
-- revoke_all_for_user, which is rare but must never become a table scan either.
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS passkey_credentials (
    credential_id TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    public_key    BLOB NOT NULL,
    sign_count    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_passkeys_user ON passkey_credentials(user_id);

-- `pending_totp_secret` is separate from `totp_secret` on purpose. Enrolment is two-step,
-- and writing an unconfirmed secret over the live one — or flipping `enabled` off to mean
-- "mid-enrolment" — would let *starting* an enrolment disable a second factor that policy
-- forbids disabling (deep-dive §4.6.1's floor). A pending secret is inert until a code
-- from the user's own authenticator promotes it; nothing about the live configuration
-- moves until then.
CREATE TABLE IF NOT EXISTS two_factor_configs (
    user_id             TEXT PRIMARY KEY,
    enabled             INTEGER NOT NULL DEFAULT 0,
    method              TEXT,
    totp_secret         TEXT,
    pending_totp_secret TEXT
);

CREATE TABLE IF NOT EXISTS break_glass_grants (
    grant_id             TEXT PRIMARY KEY,
    staff_user_id        TEXT NOT NULL,
    target_client_user_id TEXT NOT NULL,
    reason               TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    granted_at           TEXT NOT NULL,
    expires_at           TEXT NOT NULL,
    revoked_at           TEXT
);
-- check_access() is on the read path of every staff access to a client's data, so the
-- pair lookup is indexed rather than scanned.
CREATE INDEX IF NOT EXISTS idx_grants_pair
    ON break_glass_grants(staff_user_id, target_client_user_id, expires_at);

-- One table behind every in-flight challenge: OIDC state/PKCE, WebAuthn challenges, OTP
-- codes, second factors, and step-up. `purpose` is what keeps them from substituting for
-- one another; `payload` is per-method and opaque to this layer.
CREATE TABLE IF NOT EXISTS login_challenges (
    challenge_id TEXT PRIMARY KEY,
    method       TEXT NOT NULL,
    purpose      TEXT NOT NULL,
    user_id      TEXT,
    payload      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    consumed_at  TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_challenges_expiry ON login_challenges(expires_at);
"""


def default_db_path() -> Path:
    """Top-level installation directory, never inside a release clone (§1.6, §5.2).

    `RESIBO_TOP_LEVEL` is how Supervisor tells a service where the shared top level is. The
    fallback keeps a bare developer checkout runnable without pretending the repo is the
    right home for identity data — it resolves outside the repo, never into `data/`.
    """
    top = os.environ.get("RESIBO_TOP_LEVEL")
    base = Path(top) if top else Path.home() / ".resibo"
    return base / "auth.sqlite"


async def in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run blocking work off the event loop.

    Two separate reasons this exists as one helper rather than scattered `to_thread` calls:
    SQLite access is a blocking syscall, and — the rule stated for this API specifically —
    any deliberately CPU-expensive cryptographic work must not run on the loop, or it
    stalls every other concurrent request. Passkey signature verification goes through
    here for that second reason, not the first.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class AuthDatabase:
    """Owns the one connection to Auth's database. Nothing outside this file sees it."""

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
        self._ensure_columns()
        self._conn.commit()

    def _ensure_columns(self) -> None:
        """Add columns `CREATE TABLE IF NOT EXISTS` cannot add to a database that already
        exists. Idempotent, and deliberately additive only — this is the same field-only-append
        discipline the `.proto` follows, applied to the schema."""
        for table, column, decl in (
            ("two_factor_configs", "pending_totp_secret", "TEXT"),
        ):
            existing = {
                r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")
            }
            if column not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- guarded primitives, the only way any sibling module reaches the connection ----
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

    def explain(self, sql: str, params: tuple | list = ()) -> list[str]:
        """Query-plan text. Exists for the §11 testing hook that asserts `ValidateSession`
        stays a single indexed read rather than degrading into a scan — an assertion the
        test can make directly instead of inferring it from a timing measurement."""
        with self._lock:
            rows = self._conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        return [r["detail"] for r in rows]


class UserDirectory:
    """Users, their passkeys, and their 2FA configuration. No credentials of any other kind
    exist to store."""

    def __init__(self, db: AuthDatabase) -> None:
        self._db = db

    # ----------------------------------------------------------------- users
    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(
            user_id=row["user_id"], role=Role(row["role"]), email=row["email"],
            phone_number=row["phone_number"], sso_provider=row["sso_provider"],
            sso_subject=row["sso_subject"],
            created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
        )

    def create_user(self, user: User) -> User:
        self._db.write(
            "INSERT INTO users (user_id, role, email, phone_number, sso_provider,"
            " sso_subject, created_at) VALUES (?,?,?,?,?,?,?)",
            (user.user_id, user.role.value, user.email, user.phone_number,
             user.sso_provider, user.sso_subject, user.created_at.isoformat()),
        )
        return user

    def get(self, user_id: str) -> User | None:
        row = self._db.query_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return self._row_to_user(row) if row else None

    def find_by_email(self, email: str) -> User | None:
        row = self._db.query_one("SELECT * FROM users WHERE email = ?", (email,))
        return self._row_to_user(row) if row else None

    def find_by_phone(self, phone_number: str) -> User | None:
        row = self._db.query_one(
            "SELECT * FROM users WHERE phone_number = ?", (phone_number,)
        )
        return self._row_to_user(row) if row else None

    def find_by_sso_subject(self, provider: str, subject: str) -> User | None:
        """The real SSO identity lookup. Keyed on `sub`, never on `email` (§4.2)."""
        row = self._db.query_one(
            "SELECT * FROM users WHERE sso_provider = ? AND sso_subject = ?",
            (provider, subject),
        )
        return self._row_to_user(row) if row else None

    def sync_email(self, user_id: str, email: str) -> None:
        """Re-synced from the latest ID token on every SSO login. Safe precisely because
        identity is keyed on the subject — this updates a display/contact field, it does
        not move the user."""
        self._db.write("UPDATE users SET email = ? WHERE user_id = ?", (email, user_id))

    def set_role(self, user_id: str, role: Role) -> None:
        """Deliberately not public API for role changes. `roles/role_check.py`'s
        `change_user_role()` is, because it also revokes the user's sessions — which
        deep-dive §5.3 makes a hard requirement, not a caller's responsibility to remember.
        """
        self._db.write("UPDATE users SET role = ? WHERE user_id = ?", (role.value, user_id))

    # ------------------------------------------------------------- passkeys
    def add_passkey(self, credential: PasskeyCredential) -> None:
        self._db.write(
            "INSERT INTO passkey_credentials (credential_id, user_id, public_key,"
            " sign_count, created_at) VALUES (?,?,?,?,?)",
            (credential.credential_id, credential.user_id, credential.public_key,
             credential.sign_count, credential.created_at.isoformat()),
        )

    def get_passkey(self, credential_id: str) -> PasskeyCredential | None:
        row = self._db.query_one(
            "SELECT * FROM passkey_credentials WHERE credential_id = ?", (credential_id,)
        )
        if not row:
            return None
        return PasskeyCredential(
            credential_id=row["credential_id"], user_id=row["user_id"],
            public_key=bytes(row["public_key"]), sign_count=int(row["sign_count"]),
            created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
        )

    def list_passkeys(self, user_id: str) -> list[str]:
        rows = self._db.query_all(
            "SELECT credential_id FROM passkey_credentials WHERE user_id = ?", (user_id,)
        )
        return [r["credential_id"] for r in rows]

    def update_sign_count(self, credential_id: str, sign_count: int) -> None:
        self._db.write(
            "UPDATE passkey_credentials SET sign_count = ? WHERE credential_id = ?",
            (sign_count, credential_id),
        )

    # ------------------------------------------------------------ 2FA state
    def get_two_factor(self, user_id: str) -> TwoFactorConfig:
        row = self._db.query_one(
            "SELECT * FROM two_factor_configs WHERE user_id = ?", (user_id,)
        )
        if not row:
            return TwoFactorConfig(user_id=user_id, enabled=False, method=None)
        return TwoFactorConfig(
            user_id=user_id, enabled=bool(row["enabled"]), method=row["method"]
        )

    def get_totp_secret(self, user_id: str) -> str | None:
        row = self._db.query_one(
            "SELECT totp_secret FROM two_factor_configs WHERE user_id = ?", (user_id,)
        )
        return row["totp_secret"] if row else None

    def set_pending_totp_secret(self, user_id: str, secret: str) -> None:
        """Park an unconfirmed enrolment secret without touching the live configuration.

        Nothing about `enabled`, `method`, or `totp_secret` moves here. That is the whole
        point: beginning an enrolment must not be a way to switch a second factor off that
        `TwoFactorGate.configure()` would refuse to switch off (deep-dive §4.6.1).
        """
        self._db.write(
            "INSERT INTO two_factor_configs (user_id, enabled, method, pending_totp_secret)"
            " VALUES (?,0,NULL,?) ON CONFLICT(user_id) DO UPDATE SET"
            " pending_totp_secret=excluded.pending_totp_secret",
            (user_id, secret),
        )

    def get_pending_totp_secret(self, user_id: str) -> str | None:
        row = self._db.query_one(
            "SELECT pending_totp_secret FROM two_factor_configs WHERE user_id = ?", (user_id,)
        )
        return row["pending_totp_secret"] if row else None

    def promote_pending_totp_secret(self, user_id: str) -> bool:
        """Confirmation: the pending secret becomes the live one and 2FA turns on, in one
        statement so there is no window where the config is enabled against no secret."""
        return self._db.write(
            "UPDATE two_factor_configs SET totp_secret = pending_totp_secret,"
            " pending_totp_secret = NULL, enabled = 1, method = 'totp'"
            " WHERE user_id = ? AND pending_totp_secret IS NOT NULL",
            (user_id,),
        ) == 1

    def set_two_factor(self, config: TwoFactorConfig, totp_secret: str | None = None) -> None:
        self._db.write(
            "INSERT INTO two_factor_configs (user_id, enabled, method, totp_secret)"
            " VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET"
            " enabled=excluded.enabled, method=excluded.method,"
            " totp_secret=COALESCE(excluded.totp_secret, two_factor_configs.totp_secret)",
            (config.user_id, int(config.enabled), config.method, totp_secret),
        )


__all__ = ["AuthDatabase", "UserDirectory", "default_db_path", "in_thread", "utcnow"]

"""Issue, authenticate, and revoke agent tokens (`v3-deepdive-55-agent-control-api.md` §3).

Three properties here are structural rather than policy, and all three should stay that way:

1. **A token is always issued by a real human**, through the normal settings surface. There
   is no self-provisioning path — `issue_token` requires an `issued_by` user id and the
   gRPC service checks the caller's own owner/staff session before reaching this module.
2. **A token can never carry `owner`** (§3.1). Enforced twice on purpose: the `AgentRole`
   type excludes it, this module rejects it explicitly, and the database has a CHECK
   constraint. `docs/PRINCIPLES.md` §4.5 prefers structural guarantees where available.
3. **Only a hash is stored.** The plaintext is returned once and is not recoverable.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from .contracts import AgentRole, AgentToken, IssuedToken, utcnow
from .errors import OwnerRoleForbidden, TokenExpired, TokenRevoked, UnknownToken
from .store import AgentStore

TOKEN_PREFIX = "rsb_agent_"
_TOKEN_BYTES = 32


def hash_token(plaintext: str) -> str:
    """SHA-256, matching the hash choice made everywhere else in this project — not MD5
    (broken), not SHA-512 (needlessly large)."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


class TokenLifecycle:
    def __init__(self, store: AgentStore) -> None:
        self._store = store

    def issue_token(
        self,
        *,
        issued_by: str,
        issued_to_label: str,
        scopes: tuple[str, ...],
        role: AgentRole = "staff",
        expires_in: timedelta | None = None,
    ) -> IssuedToken:
        if role not in ("client", "staff"):
            # Covers "owner" and anything else. Phrased as a hard ceiling rather than a
            # permission check because that is what §3.1 actually specifies: an owner who
            # wants an owner-level action performed does it themselves.
            raise OwnerRoleForbidden(
                f"agent tokens may only carry 'client' or 'staff'; refused {role!r}. "
                "An agent is never more capable than the human who authorized it."
            )
        if not issued_by:
            raise ValueError("issued_by is required — a token is always issued by a real human")

        plaintext = TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
        now = utcnow()
        token = AgentToken(
            token_id=secrets.token_hex(8),
            issued_by=issued_by,
            issued_to_label=issued_to_label,
            scopes=tuple(scopes),
            role=role,
            issued_at=now,
            expires_at=(now + expires_in) if expires_in else None,
        )
        self._store.insert_token(token, hash_token(plaintext))
        return IssuedToken(token=token, plaintext=plaintext)

    def authenticate(self, plaintext: str) -> AgentToken:
        """Raises rather than returning an error object — the one deliberate exception to
        errors-as-data (`docs/PRINCIPLES.md` §4.1), matching Auth & Tenancy's own carve-out.
        A caller that silently proceeds past a failed auth check is a worse outcome than one
        that ignores a business-logic error."""
        token = self._store.find_by_hash(hash_token(plaintext))
        if token is None:
            raise UnknownToken("no such agent token")
        now = utcnow()
        if token.revoked_at is not None and token.revoked_at <= now:
            raise TokenRevoked(f"agent token {token.token_id} was revoked at {token.revoked_at.isoformat()}")
        if token.expires_at is not None and token.expires_at <= now:
            raise TokenExpired(f"agent token {token.token_id} expired at {token.expires_at.isoformat()}")
        return token

    def revoke(self, token_id: str) -> bool:
        """Idempotent. Returns False if the token was already revoked or never existed."""
        return self._store.revoke(token_id) is not None

    def list_tokens(self, include_inactive: bool = True) -> list[AgentToken]:
        return self._store.list_tokens(include_inactive)

"""In-flight challenge storage, shared by every authentication method.

One table serves the OIDC `state`/PKCE verifier, the WebAuthn challenge, the email/SMS
one-time code, the second factor, and step-up re-authentication — because they are the same
shape: a short-lived, single-use, attempt-limited record that a later request redeems
exactly once.

Three properties are enforced here rather than in each provider, so a new method cannot
accidentally ship without them:

- **Single use.** `consume()` is a conditional UPDATE, so two concurrent redemptions of the
  same challenge cannot both win — the second sees zero rows affected.
- **Expiry.** Checked on read against the stored timestamp, never by trusting a sweep to
  have run recently. The sweep (`purge_expired()`, registered as a Background Workers job)
  is housekeeping; it is not the security boundary. Same reasoning as break-glass expiry.
- **Purpose separation.** A `STEP_UP` challenge cannot be redeemed as a `LOGIN` and vice
  versa. Without this, §4.5's step-up gate would be satisfiable by replaying an ordinary
  login — which is exactly the bypass its own testing hook exists to catch.

Failures here are returned as `AuthError` values, not raised: a challenge that cannot be
redeemed yields no session, so a caller ignoring the error is not thereby authenticated
(`errors.py` states the full raise/return split).
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from common.frozen_dict import FrozenDict

from .contracts import AuthError, AuthMethod, ChallengePurpose, utcnow
from .store import AuthDatabase

#: Attempts allowed against one challenge before it is dead. Applies to every method, but
#: it is the numeric OTP codes it actually matters for — six digits is a small space and
#: unlimited guesses would make the length meaningless.
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class StoredChallenge:
    challenge_id: str
    method: AuthMethod
    purpose: ChallengePurpose
    user_id: str | None
    payload: FrozenDict
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None
    attempts: int


class ChallengeStore:
    def __init__(self, db: AuthDatabase) -> None:
        self._db = db

    def create(
        self,
        method: AuthMethod,
        purpose: ChallengePurpose,
        payload: dict,
        ttl_seconds: int,
        user_id: str | None = None,
    ) -> StoredChallenge:
        now = utcnow()
        challenge = StoredChallenge(
            #: 256 bits from the OS CSPRNG. Never derived from the user, the method, or a
            #: counter — a guessable challenge id is a guessable redemption.
            challenge_id=secrets.token_urlsafe(32),
            method=method,
            purpose=purpose,
            user_id=user_id,
            payload=FrozenDict(dict(payload)),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            consumed_at=None,
            attempts=0,
        )
        self._db.write(
            "INSERT INTO login_challenges (challenge_id, method, purpose, user_id,"
            " payload, created_at, expires_at, consumed_at, attempts)"
            " VALUES (?,?,?,?,?,?,?,NULL,0)",
            (challenge.challenge_id, method.value, purpose.value, user_id,
             json.dumps(dict(payload)), now.isoformat(), challenge.expires_at.isoformat()),
        )
        return challenge

    def _row_to_challenge(self, row) -> StoredChallenge:
        return StoredChallenge(
            challenge_id=row["challenge_id"],
            method=AuthMethod(row["method"]),
            purpose=ChallengePurpose(row["purpose"]),
            user_id=row["user_id"],
            payload=FrozenDict(json.loads(row["payload"])),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            consumed_at=(
                datetime.fromisoformat(row["consumed_at"]) if row["consumed_at"] else None
            ),
            attempts=int(row["attempts"]),
        )

    def load(
        self, challenge_id: str, purpose: ChallengePurpose | None = None
    ) -> tuple[StoredChallenge | None, AuthError | None]:
        """Fetch a challenge and say, in one place, why it cannot be used if it cannot.

        Returns `(challenge, None)` when redeemable and `(None, error)` otherwise, so no
        provider has to re-implement the expiry/consumed/attempts checks and get one of
        them subtly wrong.
        """
        row = self._db.query_one(
            "SELECT * FROM login_challenges WHERE challenge_id = ?", (challenge_id,)
        )
        if row is None:
            return None, AuthError.CHALLENGE_NOT_FOUND
        challenge = self._row_to_challenge(row)
        if purpose is not None and challenge.purpose is not purpose:
            # Reported as "not found", not "wrong purpose": a caller probing which
            # challenge ids exist for which purpose learns nothing from this response.
            return None, AuthError.CHALLENGE_NOT_FOUND
        if challenge.consumed_at is not None:
            return None, AuthError.CHALLENGE_CONSUMED
        if challenge.expires_at <= utcnow():
            return None, AuthError.CHALLENGE_EXPIRED
        if challenge.attempts >= MAX_ATTEMPTS:
            return None, AuthError.TOO_MANY_ATTEMPTS
        return challenge, None

    def record_attempt(self, challenge_id: str) -> int:
        """Counted *before* the answer is checked, so a wrong answer costs an attempt even
        if the process handling it dies immediately afterwards."""
        self._db.write(
            "UPDATE login_challenges SET attempts = attempts + 1 WHERE challenge_id = ?",
            (challenge_id,),
        )
        row = self._db.query_one(
            "SELECT attempts FROM login_challenges WHERE challenge_id = ?", (challenge_id,)
        )
        return int(row["attempts"]) if row else 0

    def consume(self, challenge_id: str) -> bool:
        """Single-use redemption. `False` means someone else got there first."""
        rows = self._db.write(
            "UPDATE login_challenges SET consumed_at = ?"
            " WHERE challenge_id = ? AND consumed_at IS NULL",
            (utcnow().isoformat(), challenge_id),
        )
        return rows == 1

    def purge_expired(self, older_than: datetime | None = None) -> int:
        """Housekeeping only — registered as a Background Workers job (deep-dive §6.3).
        Nothing above depends on it having run."""
        cutoff = (older_than or utcnow()).isoformat()
        return self._db.write(
            "DELETE FROM login_challenges WHERE expires_at <= ?", (cutoff,)
        )


__all__ = ["MAX_ATTEMPTS", "ChallengeStore", "StoredChallenge"]

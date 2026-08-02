"""The shared one-time-code engine behind both the email and SMS login providers.

Deep-dive §4.4 specifies email and SMS as *the same underlying shape* — a short-lived,
single-use numeric code delivered over a channel and typed back into the form. This module
is that shape, once; `email_login_provider.py` and `sms_login_provider.py` are the two thin
bindings that pick a channel and an identifier field. Writing the machinery twice would be
two places for the single-use rule to be subtly different.

**Codes, deliberately not magic links.** A link-based flow has a real, recurring failure
mode: email security scanners and link-preview bots pre-fetch the URL and burn the
single-use token before the human ever clicks it. A typed code cannot be consumed by
something that merely looked at the message.

**Account enumeration is not leaked.** An unknown address gets a challenge that looks
exactly like a real one, with no code ever sent and no code that can satisfy it. The
alternative — returning `UNKNOWN_USER` — turns the login form into a free membership oracle
for anyone with a list of email addresses. The deep-dive does not settle this; this is the
defensible reading of "fail closed" applied to an information leak rather than an access
grant, and it is called out here because it is a real choice, not an obvious default.

The code is stored only as a salted SHA-256 digest and compared with `hmac.compare_digest`,
so neither the database nor a timing measurement yields it. This is cheap hashing over a
high-entropy salt, not a password KDF — there are no passwords here to stretch, and nothing
in this module belongs in the "deliberately expensive crypto, keep it off the loop"
category `base.off_event_loop` exists for.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable

from common.frozen_dict import FrozenDict

from ..challenges import ChallengeStore
from ..contracts import (
    AuthChallenge,
    AuthError,
    AuthMethod,
    AuthResult,
    ChallengePurpose,
    User,
)
from ..store import in_thread
from .notifications import NotificationChannel

#: What the user sees. Kept here rather than in the providers so both channels word it the
#: same way, and short because an SMS is a single segment or it is two.
_SUBJECT = "Your sign-in code"


def _hash_code(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def generate_code(length: int) -> str:
    """A uniformly random decimal code of exactly `length` digits, leading zeros kept.

    `secrets.randbelow` rather than `random`: the module without the CSPRNG has no business
    anywhere near this file, and a code that is predictable from a seed is not a factor.
    """
    if length < 4:
        raise ValueError("OTP code length must be at least 4 digits")
    return str(secrets.randbelow(10**length)).zfill(length)


class OtpProvider:
    """Concrete `AuthMethodProvider` for a code delivered over one channel.

    `lookup_user` is injected rather than the directory being queried directly, because the
    email provider looks a user up by address and the SMS provider by phone number — the one
    genuine difference between them, expressed as one argument instead of a subclass.
    """

    def __init__(
        self,
        method: AuthMethod,
        channel: NotificationChannel,
        challenges: ChallengeStore,
        lookup_user: Callable[[str], User | None],
        code_length: int = 6,
        ttl_seconds: int = 300,
    ) -> None:
        self._method = method
        self._channel = channel
        self._challenges = challenges
        self._lookup_user = lookup_user
        self._code_length = code_length
        self._ttl = ttl_seconds

    @property
    def method(self) -> AuthMethod:
        return self._method

    async def is_available(self) -> bool:
        return await self._channel.is_available()

    async def initiate(
        self, identifier: str, purpose: ChallengePurpose = ChallengePurpose.LOGIN
    ) -> AuthChallenge:
        if not await self._channel.is_available():
            return AuthChallenge.failure(
                self._method, AuthError.METHOD_UNAVAILABLE,
                f"{self._channel.name} channel is unavailable", purpose,
            )

        user = await in_thread(self._lookup_user, identifier)
        code = generate_code(self._code_length)
        salt = secrets.token_hex(8)
        payload = {
            "salt": salt,
            # A decoy carries a hash of a code that was never sent anywhere. Nothing
            # distinguishes it from the outside, and nothing can satisfy it.
            "code_hash": _hash_code(salt, code),
            "decoy": user is None,
            "identifier": identifier,
        }
        stored = await in_thread(
            self._challenges.create, self._method, purpose, payload, self._ttl,
            user.user_id if user else None,
        )

        if user is not None:
            delivered = await self._channel.send(
                identifier, _SUBJECT, f"{code} — expires in {self._ttl // 60} minutes."
            )
            if not delivered:
                # Delivery failed after the challenge existed: report the method as
                # unavailable rather than leaving the user staring at a code entry box for
                # a message that is never arriving.
                return AuthChallenge.failure(
                    self._method, AuthError.METHOD_UNAVAILABLE,
                    f"{self._channel.name} delivery failed", purpose,
                )

        return AuthChallenge(
            challenge_id=stored.challenge_id,
            method=self._method,
            purpose=purpose,
            user_id=None,  # never echoed back before the code is proven
            expires_at=stored.expires_at,
            parameters=FrozenDict({
                "channel": self._channel.name,
                "code_length": self._code_length,
            }),
        )

    async def verify(self, challenge_id: str, response: str) -> AuthResult:
        stored, error = await in_thread(self._challenges.load, challenge_id)
        if error is not None or stored is None:
            return AuthResult.failure(self._method, error or AuthError.CHALLENGE_NOT_FOUND)

        purpose = stored.purpose
        attempts = await in_thread(self._challenges.record_attempt, challenge_id)
        expected = str(stored.payload.get("code_hash", ""))
        salt = str(stored.payload.get("salt", ""))
        presented = _hash_code(salt, (response or "").strip())

        if not hmac.compare_digest(presented, expected) or stored.payload.get("decoy"):
            return AuthResult.failure(
                self._method, AuthError.CODE_INVALID,
                f"attempt {attempts}", purpose,
            )
        if not await in_thread(self._challenges.consume, challenge_id):
            # Someone else redeemed it between the load and here. Single use means single
            # use even under a race.
            return AuthResult.failure(self._method, AuthError.CHALLENGE_CONSUMED, "", purpose)

        return AuthResult(
            authenticated=True,
            method=self._method,
            purpose=purpose,
            user_id=stored.user_id,
            claims=FrozenDict({"channel": self._channel.name}),
        )


__all__ = ["OtpProvider", "generate_code"]

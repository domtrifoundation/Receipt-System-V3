"""Passkey login — WebAuthn/FIDO2 via `py_webauthn`, behind one adapter (deep-dive §4.3).

A passkey proves possession of a private key that never leaves the user's own device. No
shared secret is transmitted, stored, or guessable — which is a security property the other
three methods genuinely do not have: SSO depends on an identity provider being trustworthy
at the moment of use, and an OTP depends on a delivery channel being. A passkey depends on
nothing external at all.

**Library choice**: `py_webauthn` (Duo Security's), resolved in the deep-dive's §12. It is
imported lazily inside `PyWebAuthnEngine` and every call goes through the `WebAuthnEngine`
Protocol, so an install without it degrades passkeys to unavailable rather than failing at
startup (`docs/PRINCIPLES.md` §1.3, §3.3 point 5, §4.4), and the tests substitute a fake
engine instead of performing real ceremonies.

**Signature verification runs off the event loop.** Elliptic-curve verification is fast, but
this API's stated rule is that deliberately expensive cryptographic work never executes on
the loop, and "fast today" is not a property to build a hot path on when the cost is one
`off_event_loop` call. (The genuinely expensive operation in most auth systems — password
hashing — does not exist here at all.)

**The sign counter is checked, not just stored.** A counter that fails to advance is the
standard cloned-authenticator signal, and discarding it would throw away the only anti-replay
evidence the ceremony produces. Authenticators that always report zero are permitted, since
that is a legitimate, common implementation — the check applies only when the authenticator
claims to keep a counter at all.
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol

from common.frozen_dict import FrozenDict

from ..challenges import ChallengeStore
from ..contracts import (
    AuthChallenge,
    AuthError,
    AuthMethod,
    AuthResult,
    ChallengePurpose,
    PasskeyCredential,
)
from ..store import UserDirectory, in_thread
from .base import off_event_loop

CEREMONY_TTL_SECONDS = 300


@dataclass(frozen=True)
class VerifiedRegistration:
    credential_id: str
    public_key: bytes
    sign_count: int


class WebAuthnEngine(Protocol):
    """Everything Auth needs from a WebAuthn library, and nothing more.

    Deliberately synchronous: these are CPU operations, not I/O, and the caller is what
    decides they belong in a worker thread. An engine that hid its own threading would take
    that decision away from the one place that should be making it.
    """

    def registration_options(self, user_id: str, user_name: str, rp_id: str, challenge: bytes) -> dict: ...

    def verify_registration(
        self, response: str, expected_challenge: bytes, rp_id: str, origin: str
    ) -> VerifiedRegistration: ...

    def authentication_options(
        self, credential_ids: list[str], rp_id: str, challenge: bytes
    ) -> dict: ...

    def verify_authentication(
        self, response: str, expected_challenge: bytes, public_key: bytes,
        current_sign_count: int, rp_id: str, origin: str,
    ) -> int: ...


@dataclass
class PyWebAuthnEngine:
    """The only place `py_webauthn` is touched."""

    rp_name: str = "DOMTRI Resibo"
    _module: Any = field(default=None, repr=False)

    @staticmethod
    def available() -> bool:
        try:
            import webauthn  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    def _webauthn(self):
        if self._module is None:
            import webauthn  # noqa: PLC0415

            self._module = webauthn
        return self._module

    def registration_options(
        self, user_id: str, user_name: str, rp_id: str, challenge: bytes
    ) -> dict:
        w = self._webauthn()
        options = w.generate_registration_options(
            rp_id=rp_id, rp_name=self.rp_name, user_id=user_id.encode(),
            user_name=user_name, challenge=challenge,
        )
        return {"publicKey": w.options_to_json(options)}

    def verify_registration(
        self, response: str, expected_challenge: bytes, rp_id: str, origin: str
    ) -> VerifiedRegistration:
        w = self._webauthn()
        verified = w.verify_registration_response(
            credential=response, expected_challenge=expected_challenge,
            expected_rp_id=rp_id, expected_origin=origin,
        )
        return VerifiedRegistration(
            credential_id=base64.urlsafe_b64encode(verified.credential_id).decode().rstrip("="),
            public_key=verified.credential_public_key,
            sign_count=int(verified.sign_count),
        )

    def authentication_options(
        self, credential_ids: list[str], rp_id: str, challenge: bytes
    ) -> dict:
        w = self._webauthn()
        options = w.generate_authentication_options(rp_id=rp_id, challenge=challenge)
        return {"publicKey": w.options_to_json(options), "credential_ids": credential_ids}

    def verify_authentication(
        self, response: str, expected_challenge: bytes, public_key: bytes,
        current_sign_count: int, rp_id: str, origin: str,
    ) -> int:
        w = self._webauthn()
        verified = w.verify_authentication_response(
            credential=response, expected_challenge=expected_challenge,
            expected_rp_id=rp_id, expected_origin=origin,
            credential_public_key=public_key, credential_current_sign_count=current_sign_count,
        )
        return int(verified.new_sign_count)


class PasskeyProvider:
    """`AuthMethodProvider` for WebAuthn, plus the registration ceremony.

    Registration is not on the `AuthMethodProvider` Protocol on purpose: enrolling a
    credential is not proving an identity, and putting it on the shared interface would
    force every other provider to carry a concept only this one has.
    """

    def __init__(
        self,
        challenges: ChallengeStore,
        directory: UserDirectory,
        rp_id: str = "",
        origin: str = "",
        engine: WebAuthnEngine | None = None,
    ) -> None:
        self._challenges = challenges
        self._directory = directory
        self._rp_id = rp_id
        self._origin = origin or (f"https://{rp_id}" if rp_id else "")
        self._engine = engine

    @property
    def method(self) -> AuthMethod:
        return AuthMethod.PASSKEY

    def _resolve_engine(self) -> WebAuthnEngine | None:
        if self._engine is not None:
            return self._engine
        if not PyWebAuthnEngine.available():
            return None
        self._engine = PyWebAuthnEngine()
        return self._engine

    async def is_available(self) -> bool:
        return bool(self._rp_id) and self._resolve_engine() is not None

    # ------------------------------------------------------------ enrolment
    async def begin_registration(self, user_id: str) -> AuthChallenge:
        engine = self._resolve_engine()
        user = await in_thread(self._directory.get, user_id)
        if engine is None or not self._rp_id:
            return AuthChallenge.failure(
                AuthMethod.PASSKEY, AuthError.METHOD_UNAVAILABLE,
                "no WebAuthn engine available or rp_id is unset",
                ChallengePurpose.REGISTRATION,
            )
        if user is None:
            return AuthChallenge.failure(
                AuthMethod.PASSKEY, AuthError.UNKNOWN_USER, "", ChallengePurpose.REGISTRATION
            )
        raw = secrets.token_bytes(32)
        stored = await in_thread(
            self._challenges.create, AuthMethod.PASSKEY, ChallengePurpose.REGISTRATION,
            {"challenge": base64.b64encode(raw).decode()}, CEREMONY_TTL_SECONDS, user_id,
        )
        options = await off_event_loop(
            engine.registration_options, user_id, user.email, self._rp_id, raw
        )
        return AuthChallenge(
            challenge_id=stored.challenge_id, method=AuthMethod.PASSKEY,
            purpose=ChallengePurpose.REGISTRATION, user_id=user_id,
            expires_at=stored.expires_at, parameters=FrozenDict(options),
        )

    async def complete_registration(self, challenge_id: str, response: str) -> AuthResult:
        stored, error = await in_thread(
            self._challenges.load, challenge_id, ChallengePurpose.REGISTRATION
        )
        if error is not None or stored is None:
            return AuthResult.failure(
                AuthMethod.PASSKEY, error or AuthError.CHALLENGE_NOT_FOUND, "",
                ChallengePurpose.REGISTRATION,
            )
        engine = self._resolve_engine()
        if engine is None:
            return AuthResult.failure(
                AuthMethod.PASSKEY, AuthError.METHOD_UNAVAILABLE, "",
                ChallengePurpose.REGISTRATION,
            )
        await in_thread(self._challenges.record_attempt, challenge_id)
        raw = base64.b64decode(str(stored.payload.get("challenge", "")))
        try:
            verified = await off_event_loop(
                engine.verify_registration, response, raw, self._rp_id, self._origin
            )
        except Exception as exc:  # noqa: BLE001 - a failed ceremony is a failed attempt
            return AuthResult.failure(
                AuthMethod.PASSKEY, AuthError.PASSKEY_VERIFICATION_FAILED,
                f"{type(exc).__name__}: {exc}", ChallengePurpose.REGISTRATION,
            )
        if not await in_thread(self._challenges.consume, challenge_id):
            return AuthResult.failure(
                AuthMethod.PASSKEY, AuthError.CHALLENGE_CONSUMED, "",
                ChallengePurpose.REGISTRATION,
            )
        await in_thread(self._directory.add_passkey, PasskeyCredential(
            credential_id=verified.credential_id, user_id=str(stored.user_id),
            public_key=verified.public_key, sign_count=verified.sign_count,
        ))
        return AuthResult(
            authenticated=True, method=AuthMethod.PASSKEY,
            purpose=ChallengePurpose.REGISTRATION, user_id=stored.user_id,
            claims=FrozenDict({"credential_id": verified.credential_id}),
        )

    # --------------------------------------------------------------- login
    async def initiate(
        self, identifier: str, purpose: ChallengePurpose = ChallengePurpose.LOGIN
    ) -> AuthChallenge:
        """`identifier` is the user id whose credentials are being challenged."""
        engine = self._resolve_engine()
        if engine is None or not self._rp_id:
            return AuthChallenge.failure(
                AuthMethod.PASSKEY, AuthError.METHOD_UNAVAILABLE,
                "no WebAuthn engine available or rp_id is unset", purpose,
            )
        credential_ids = await in_thread(self._directory.list_passkeys, identifier)
        raw = secrets.token_bytes(32)
        stored = await in_thread(
            self._challenges.create, AuthMethod.PASSKEY, purpose,
            {"challenge": base64.b64encode(raw).decode()}, CEREMONY_TTL_SECONDS,
            identifier or None,
        )
        options = await off_event_loop(
            engine.authentication_options, list(credential_ids), self._rp_id, raw
        )
        return AuthChallenge(
            challenge_id=stored.challenge_id, method=AuthMethod.PASSKEY, purpose=purpose,
            user_id=None, expires_at=stored.expires_at, parameters=FrozenDict(options),
        )

    async def verify(self, challenge_id: str, response: str) -> AuthResult:
        stored, error = await in_thread(self._challenges.load, challenge_id)
        if error is not None or stored is None:
            return AuthResult.failure(AuthMethod.PASSKEY, error or AuthError.CHALLENGE_NOT_FOUND)
        purpose = stored.purpose
        engine = self._resolve_engine()
        if engine is None:
            return AuthResult.failure(AuthMethod.PASSKEY, AuthError.METHOD_UNAVAILABLE, "", purpose)
        await in_thread(self._challenges.record_attempt, challenge_id)

        credential_id = _credential_id_of(response)
        credential = (
            await in_thread(self._directory.get_passkey, credential_id)
            if credential_id else None
        )
        if credential is None:
            return AuthResult.failure(
                AuthMethod.PASSKEY, AuthError.PASSKEY_VERIFICATION_FAILED,
                "no such credential", purpose,
            )
        raw = base64.b64decode(str(stored.payload.get("challenge", "")))
        try:
            new_count = await off_event_loop(
                engine.verify_authentication, response, raw, credential.public_key,
                credential.sign_count, self._rp_id, self._origin,
            )
        except Exception as exc:  # noqa: BLE001 - a failed ceremony is a failed attempt
            return AuthResult.failure(
                AuthMethod.PASSKEY, AuthError.PASSKEY_VERIFICATION_FAILED,
                f"{type(exc).__name__}: {exc}", purpose,
            )
        if credential.sign_count > 0 and new_count <= credential.sign_count:
            # The counter did not advance. Standard cloned-authenticator signal — refuse,
            # and leave the credential in place for a human to decide about.
            return AuthResult.failure(
                AuthMethod.PASSKEY, AuthError.PASSKEY_VERIFICATION_FAILED,
                "authenticator sign counter did not advance", purpose,
            )
        if not await in_thread(self._challenges.consume, challenge_id):
            return AuthResult.failure(AuthMethod.PASSKEY, AuthError.CHALLENGE_CONSUMED, "", purpose)
        await in_thread(self._directory.update_sign_count, credential.credential_id, new_count)
        return AuthResult(
            authenticated=True, method=AuthMethod.PASSKEY, purpose=purpose,
            user_id=credential.user_id,
            claims=FrozenDict({"credential_id": credential.credential_id}),
        )


def _credential_id_of(response: str) -> str:
    """Pull the credential id out of a WebAuthn assertion JSON blob.

    Read directly rather than through the engine because it is needed *before* verification
    — to find the public key to verify against. Nothing is trusted from it: an attacker
    naming someone else's credential id simply fails the signature check that follows.
    """
    import json  # noqa: PLC0415

    try:
        data = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("id") or data.get("rawId") or "")


__all__ = [
    "CEREMONY_TTL_SECONDS", "PasskeyProvider", "PyWebAuthnEngine", "VerifiedRegistration",
    "WebAuthnEngine",
]

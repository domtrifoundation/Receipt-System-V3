"""SSO/OIDC login — Authlib behind one adapter (deep-dive §4.2).

Three properties of this file are the reasons it exists in this shape:

**PKCE with S256 is not optional.** RFC 9700 makes it current best practice and it closes a
real attack class (authorization code interception). The verifier is generated from the OS
CSPRNG per login, the challenge is its SHA-256, and the verifier is stored server-side in
the challenge record — never sent to the browser.

**A signed, short-lived `state` is round-tripped and compared in constant time.** A mismatch
is `OIDC_STATE_MISMATCH`, a CSRF/replay indicator. It is returned as data rather than raised,
which is worth justifying rather than assuming: a failed callback produces no session, so a
caller ignoring it cannot end up authenticated. Nothing is silently tolerated — the attempt
is recorded and refused; it is the *shape* of the refusal that follows the ordinary
convention (`errors.py`).

**The IdP subject is the identity key, never the email.** `sub` is stable and never reused
even when the account's address changes; keying on email means an IdP-side address change
silently becomes a different user, or worse, collides with someone else's. Email is stored
for display and contact only and is re-synced from the latest ID token on every login. The
deep-dive's own §11 asks for a regression test on exactly this, because it is the kind of
assumption that breaks quietly.

**Authlib sits behind `OidcClient`.** Every library call is in `AuthlibOidcClient`, imported
lazily inside the method that needs it, so an install without Authlib degrades this method to
unavailable instead of failing at process start (`docs/PRINCIPLES.md` §1.3, §4.4). It is also
the seam the unit tests substitute at — "mocked at Authlib's client boundary", as §11 puts
it — with no HTTP round trip anywhere in the test suite.

**User provisioning is deliberately not here.** A successful OIDC handshake for an unknown
subject yields `UNKNOWN_USER`, not a new account. Account creation belongs to Setup's
first-run wizard and Account Guardian's self-service surface (deep-dive §1); an API that
answers "who is this" must not also be the thing that decides who gets to exist.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import parse_qsl

from common.frozen_dict import FrozenDict

from ..challenges import ChallengeStore
from ..contracts import (
    AuthChallenge,
    AuthError,
    AuthMethod,
    AuthResult,
    ChallengePurpose,
)
from ..store import UserDirectory, in_thread

#: How long a half-finished handshake stays redeemable. Short by design: the window between
#: a redirect and its callback is seconds of human interaction, not minutes.
STATE_TTL_SECONDS = 600


def pkce_pair() -> tuple[str, str]:
    """`(code_verifier, code_challenge)` for PKCE S256, per RFC 7636.

    Written out rather than delegated because it is twenty bytes of well-specified encoding
    and keeping it here means the adapter interface can stay "give me an authorization URL"
    rather than leaking library-specific PKCE plumbing into it. No cryptography is being
    invented — this is a SHA-256 and a base64url encode.
    """
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class OidcClient(Protocol):
    """The whole surface Auth needs from an OIDC library. Two calls."""

    async def authorization_url(
        self, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str: ...

    async def exchange_code(
        self, code: str, redirect_uri: str, code_verifier: str, nonce: str
    ) -> Mapping: ...


@dataclass
class OidcProviderConfig:
    """One entry of the `oidc.providers_enabled` registry (§10). Google today; a second
    provider is a new entry here and nothing else — that structural readiness is the point
    of §4.1's registry, independent of when the business decision to add one is made."""

    name: str = "google"
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    issuer: str = "https://accounts.google.com"
    #: Google's *non-sensitive* tier (deep-dive §4.7). Drive's restricted scopes belong to
    #: Ingestion API and a completely separate verification track; nothing here needs them.
    scopes: tuple[str, ...] = ("openid", "email", "profile")


@dataclass
class AuthlibOidcClient:
    """The only place Authlib is touched.

    The import is inside the methods on purpose (`docs/PRINCIPLES.md` §3.3 point 5): a
    dependency used by one optional login method should not be paid for at process start on
    an install that authenticates entirely by passkey.
    """

    config: OidcProviderConfig
    _client: object | None = field(default=None, repr=False)

    def _build(self):
        from authlib.integrations.httpx_client import AsyncOAuth2Client  # noqa: PLC0415

        if self._client is None:
            self._client = AsyncOAuth2Client(
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                scope=" ".join(self.config.scopes),
                code_challenge_method="S256",
            )
        return self._client

    @staticmethod
    def available() -> bool:
        try:
            import authlib  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def authorization_url(
        self, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        client = self._build()
        url, _ = client.create_authorization_url(
            f"{self.config.issuer}/o/oauth2/v2/auth",
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )
        return url

    async def exchange_code(
        self, code: str, redirect_uri: str, code_verifier: str, nonce: str
    ) -> Mapping:
        client = self._build()
        token = await client.fetch_token(
            f"{self.config.issuer}/o/oauth2/token",
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
        # Authlib validates the ID token's signature, issuer, audience and nonce during
        # parsing. Auth does not re-implement any of that; it reads the resulting claims.
        claims = client.parse_id_token(token, nonce=nonce)
        return dict(claims)


def _parse_callback(response: str) -> dict[str, str]:
    """Accept either a raw callback query string or a JSON object.

    Gateway hands over whichever is convenient at its own edge; normalising here keeps that
    choice from becoming a contract this API has to defend.
    """
    text = (response or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, Mapping) else {}
    return {k: v for k, v in parse_qsl(text.lstrip("?"))}


class SsoProvider:
    """`AuthMethodProvider` for OIDC."""

    def __init__(
        self,
        challenges: ChallengeStore,
        directory: UserDirectory,
        config: OidcProviderConfig | None = None,
        client: OidcClient | None = None,
    ) -> None:
        self._challenges = challenges
        self._directory = directory
        self._config = config or OidcProviderConfig()
        self._client = client

    @property
    def method(self) -> AuthMethod:
        return AuthMethod.SSO

    def _resolve_client(self) -> OidcClient | None:
        if self._client is not None:
            return self._client
        if not AuthlibOidcClient.available():
            return None
        self._client = AuthlibOidcClient(self._config)
        return self._client

    async def is_available(self) -> bool:
        if not (self._config.client_id and self._config.redirect_uri):
            return False
        return self._resolve_client() is not None

    async def initiate(
        self, identifier: str, purpose: ChallengePurpose = ChallengePurpose.LOGIN
    ) -> AuthChallenge:
        """`identifier` is the provider name (`"google"`), not a user identity — the IdP is
        what decides who the user is, which is the entire premise of delegated trust."""
        client = self._resolve_client()
        if client is None or not self._config.client_id:
            return AuthChallenge.failure(
                AuthMethod.SSO, AuthError.METHOD_UNAVAILABLE,
                "no OIDC client configured or Authlib is not installed", purpose,
            )
        provider = identifier or self._config.name
        if provider != self._config.name:
            return AuthChallenge.failure(
                AuthMethod.SSO, AuthError.METHOD_UNAVAILABLE,
                f"provider {provider!r} is not enabled", purpose,
            )

        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(16)
        verifier, code_challenge = pkce_pair()
        stored = await in_thread(
            self._challenges.create, AuthMethod.SSO, purpose,
            {"state": state, "nonce": nonce, "code_verifier": verifier,
             "provider": provider},
            STATE_TTL_SECONDS, None,
        )
        try:
            url = await client.authorization_url(
                self._config.redirect_uri, state, nonce, code_challenge
            )
        except Exception as exc:  # noqa: BLE001 - an unreachable IdP is unavailability
            return AuthChallenge.failure(
                AuthMethod.SSO, AuthError.METHOD_UNAVAILABLE,
                f"{type(exc).__name__}: {exc}", purpose,
            )

        return AuthChallenge(
            challenge_id=stored.challenge_id,
            method=AuthMethod.SSO,
            purpose=purpose,
            expires_at=stored.expires_at,
            #: `state` is echoed because the browser must send it back; the verifier and
            #: nonce are not, and never leave this process.
            parameters=FrozenDict({
                "redirect_url": url, "state": state, "provider": provider,
            }),
        )

    async def verify(self, challenge_id: str, response: str) -> AuthResult:
        stored, error = await in_thread(self._challenges.load, challenge_id)
        if error is not None or stored is None:
            return AuthResult.failure(AuthMethod.SSO, error or AuthError.CHALLENGE_NOT_FOUND)
        purpose = stored.purpose
        await in_thread(self._challenges.record_attempt, challenge_id)

        callback = _parse_callback(response)
        presented_state = callback.get("state", "")
        expected_state = str(stored.payload.get("state", ""))
        if not presented_state or not hmac.compare_digest(presented_state, expected_state):
            return AuthResult.failure(
                AuthMethod.SSO, AuthError.OIDC_STATE_MISMATCH,
                "callback state did not match the one issued for this handshake", purpose,
            )

        code = callback.get("code", "")
        if not code:
            return AuthResult.failure(
                AuthMethod.SSO, AuthError.CODE_INVALID, "callback carried no code", purpose
            )

        client = self._resolve_client()
        if client is None:
            return AuthResult.failure(AuthMethod.SSO, AuthError.METHOD_UNAVAILABLE, "", purpose)
        try:
            claims = await client.exchange_code(
                code, self._config.redirect_uri,
                str(stored.payload.get("code_verifier", "")),
                str(stored.payload.get("nonce", "")),
            )
        except Exception as exc:  # noqa: BLE001 - a failed exchange is a failed login
            return AuthResult.failure(
                AuthMethod.SSO, AuthError.CODE_INVALID,
                f"token exchange failed: {type(exc).__name__}: {exc}", purpose,
            )

        subject = str(claims.get("sub", ""))
        email = str(claims.get("email", ""))
        if not subject:
            return AuthResult.failure(
                AuthMethod.SSO, AuthError.CODE_INVALID, "ID token carried no subject", purpose
            )

        provider = str(stored.payload.get("provider", self._config.name))
        # THE identity lookup. Keyed on `sub`. Changing this to `email` would be a real
        # security regression, not a simplification — §11's regression test guards it.
        user = await in_thread(self._directory.find_by_sso_subject, provider, subject)
        if user is None:
            return AuthResult.failure(
                AuthMethod.SSO, AuthError.UNKNOWN_USER,
                "no account is linked to this identity provider subject", purpose,
            )
        if not await in_thread(self._challenges.consume, challenge_id):
            return AuthResult.failure(AuthMethod.SSO, AuthError.CHALLENGE_CONSUMED, "", purpose)
        if email and email != user.email:
            # Display/contact field only. The user did not move.
            await in_thread(self._directory.sync_email, user.user_id, email)

        return AuthResult(
            authenticated=True,
            method=AuthMethod.SSO,
            purpose=purpose,
            user_id=user.user_id,
            claims=FrozenDict({"sub": subject, "email": email, "provider": provider}),
        )


__all__ = [
    "STATE_TTL_SECONDS", "AuthlibOidcClient", "OidcClient", "OidcProviderConfig",
    "SsoProvider", "pkce_pair",
]

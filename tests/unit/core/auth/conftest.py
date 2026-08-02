"""Shared fixtures for the Auth & Tenancy unit tests.

`run()` exists instead of `pytest-asyncio` for the same reason the Audit tests give: this
repo does not carry that dependency, and adding one for what `asyncio.run` already does would
put a package into `requirements.txt` and into `noxfile.py`'s deliberately narrow
forward-compat dependency list for no behavioural gain.

**No fixture here builds a real credential of any kind, and none ever should.** The providers
are exercised against injected fakes at the library boundary — `FakeOidcClient` stands in for
Authlib, `FakeWebAuthnEngine` for `py_webauthn`, `RecordingChannel` for Notifications' own
delivery channels. There is no network call and no real IdP round trip anywhere in this
suite, which is exactly what the deep-dive's §11 asks for.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from core.auth.auth_methods.passkey_provider import VerifiedRegistration
from core.auth.challenges import ChallengeStore
from core.auth.contracts import Role, TenancyMode, TwoFactorPolicy, User
from core.auth.store import AuthDatabase, UserDirectory
from core.auth.tenancy import resolve_profile


def run(coro):
    """Drive one coroutine to completion. Each call gets its own loop, deliberately — a
    leaked loop between tests would make an ordering bug look like a flake."""
    return asyncio.run(coro)


@pytest.fixture
def db(tmp_path):
    """A real file rather than `":memory:"`.

    Several tests open the same database through two different objects (a `SessionStore` and
    a `BreakGlassLedger`, say). Two in-memory connections are two unrelated databases, so an
    in-memory path would let a cross-module test pass for the wrong reason.
    """
    database = AuthDatabase(tmp_path / "auth.sqlite")
    yield database
    database.close()


@pytest.fixture
def directory(db):
    return UserDirectory(db)


@pytest.fixture
def challenges(db):
    return ChallengeStore(db)


@pytest.fixture
def profile():
    """A private multi-tenant install: 2FA optional, 30-day sessions."""
    return resolve_profile({"tenancy_mode": "multi", "public_facing": False})


@pytest.fixture
def public_profile():
    """A publicly exposed multi-tenant install — the one with a real 2FA floor."""
    return resolve_profile({"tenancy_mode": "multi", "public_facing": True})


@pytest.fixture
def client_user(directory):
    return directory.create_user(User(
        user_id="u_client", role=Role.CLIENT, email="client@example.test",
        phone_number="+639170000001",
    ))


@pytest.fixture
def staff_user(directory):
    return directory.create_user(User(
        user_id="u_staff", role=Role.STAFF, email="staff@example.test",
        sso_provider="google", sso_subject="google-sub-staff",
    ))


@dataclass
class RecordingChannel:
    """Stands in for a Notifications API channel. Records what would have been sent."""

    channel_name: str = "email"
    up: bool = True
    sent: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.channel_name

    async def is_available(self) -> bool:
        return self.up

    async def send(self, recipient: str, subject: str, body: str) -> bool:
        if not self.up:
            return False
        self.sent.append((recipient, subject, body))
        return True

    @property
    def last_code(self) -> str:
        """The delivered code, read back the way the user would read it off their phone."""
        return self.sent[-1][2].split(" ", 1)[0]


@dataclass
class FakeOidcClient:
    """The seam §11 names: mocked at Authlib's client boundary, no HTTP anywhere."""

    claims: dict = field(default_factory=lambda: {"sub": "google-sub-staff", "email": "staff@example.test"})
    exchanges: list[tuple[str, str, str]] = field(default_factory=list)
    fail_exchange: bool = False

    async def authorization_url(
        self, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        return (
            f"https://accounts.example.test/authorize?state={state}"
            f"&code_challenge={code_challenge}&code_challenge_method=S256"
        )

    async def exchange_code(
        self, code: str, redirect_uri: str, code_verifier: str, nonce: str
    ) -> dict:
        if self.fail_exchange:
            raise RuntimeError("token exchange rejected")
        self.exchanges.append((code, code_verifier, nonce))
        return dict(self.claims)


@dataclass
class FakeWebAuthnEngine:
    """Stands in for `py_webauthn`. Signature verification is represented by the assertion
    JSON carrying the credential id we expect — the real ceremony is the library's job and
    is not what these tests are asserting about Auth."""

    credential_id: str = "cred-1"
    public_key: bytes = b"\x01\x02\x03"
    next_sign_count: int = 1
    fail: bool = False

    def registration_options(self, user_id, user_name, rp_id, challenge) -> dict:
        return {"rp_id": rp_id, "user": user_name}

    def verify_registration(self, response, expected_challenge, rp_id, origin):
        if self.fail:
            raise ValueError("registration verification failed")
        return VerifiedRegistration(self.credential_id, self.public_key, self.next_sign_count)

    def authentication_options(self, credential_ids, rp_id, challenge) -> dict:
        return {"rp_id": rp_id, "allow": list(credential_ids)}

    def verify_authentication(
        self, response, expected_challenge, public_key, current_sign_count, rp_id, origin
    ) -> int:
        if self.fail:
            raise ValueError("assertion verification failed")
        return self.next_sign_count


__all__ = [
    "FakeOidcClient", "FakeWebAuthnEngine", "RecordingChannel", "Role", "TenancyMode",
    "TwoFactorPolicy", "run",
]

"""Shared fixtures for Account Guardian's unit tests.

**Every external dependency this package has is a real cross-process gRPC call in
production** (`gateways.py`) — Auth, Audit, Persistence, Billing. None of that is exercised
here: every fixture below is a small in-memory fake implementing the matching Protocol,
following the exact seam `tests/unit/core/auth/conftest.py` uses for Authlib/WebAuthn and
`tests/unit/core/health/conftest.py` uses for its own injected clock. There is no live gRPC
server, no real Auth database, and no real Audit database anywhere in this suite — proving
this package's *own* logic (ownership checks, stage machines, audit call shape) does not
require standing up the rest of the cluster.

`run()` exists instead of `pytest-asyncio` for the same reason `core/auth/conftest.py` and
`core/audit/conftest.py` both give: this repo does not carry that dependency, and adding one
for what `asyncio.run` already does would cost a `requirements.txt` entry and a
`noxfile.py` forward-compat entry for no behavioural gain.

`FakeContext` stands in for `grpc.aio.ServicerContext`. Real `grpc.aio` contexts raise out of
`abort()` to end the RPC coroutine right there — `FakeContext.abort` reproduces exactly that
so `service.py`'s `await context.abort(...)` behaves identically to the real thing, and a
test asserting "this RPC aborted" can do it with a plain `pytest.raises`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from core.account_guardian.contracts import CallerSession, ExportOutcome, Role
from core.account_guardian.gateways import AuditOutcome, BillingClearance, RawSession
from core.account_guardian.store import AccountGuardianDatabase
from core.auth.errors import SessionExpired, SessionInvalid


def run(coro):
    """Drive one coroutine to completion. Each call gets its own loop, deliberately — a
    leaked loop between tests would make an ordering bug look like a flake."""
    return asyncio.run(coro)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Aborted(Exception):
    """What `FakeContext.abort` raises — the same "abort ends the coroutine right there"
    property a real `grpc.aio.ServicerContext` has."""

    def __init__(self, code, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class FakeContext:
    async def abort(self, code, detail: str = ""):
        raise Aborted(code, detail)


@pytest.fixture
def context() -> FakeContext:
    return FakeContext()


@pytest.fixture
def db(tmp_path) -> AccountGuardianDatabase:
    """A real file, not `":memory:"` — this package's own convention throughout (`store.py`),
    matching why `core/auth/conftest.py` and `core/audit/conftest.py` both do the same: two
    `":memory:"` connections are two unrelated databases the moment two objects open one
    each, and several tests here exercise this database through more than one module."""
    database = AccountGuardianDatabase(tmp_path / "account_guardian.sqlite")
    yield database
    database.close()


@dataclass
class FakeSessionGateway:
    """Implements `gateways.SessionGateway`. Seeded with `{session_id: (user_id, role)}` —
    real enough to exercise ownership checks, unlike `gateways.GrpcSessionGateway`, which has
    no way to list sessions at all yet (`gateways.py`'s own documented gap)."""

    sessions: dict[str, tuple[str, Role]] = field(default_factory=dict)
    revoked: list[str] = field(default_factory=list)
    unavailable: bool = False

    async def validate(self, session_id: str) -> CallerSession:
        if session_id not in self.sessions:
            raise SessionInvalid(f"no such session {session_id!r}")
        user_id, role = self.sessions[session_id]
        return CallerSession(session_id=session_id, user_id=user_id, role=role)

    async def revoke(self, session_id: str) -> bool:
        if self.unavailable:
            from core.account_guardian.errors import DependencyUnavailable

            raise DependencyUnavailable("auth service unreachable (fake)")
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.revoked.append(session_id)
            return True
        return False

    async def revoke_all_for_user(self, user_id: str) -> int:
        if self.unavailable:
            from core.account_guardian.errors import DependencyUnavailable

            raise DependencyUnavailable("auth service unreachable (fake)")
        ids = [sid for sid, (uid, _role) in self.sessions.items() if uid == user_id]
        for sid in ids:
            del self.sessions[sid]
            self.revoked.append(sid)
        return len(ids)

    async def list_sessions(self, user_id: str) -> tuple[RawSession, ...]:
        now = utcnow()
        return tuple(
            RawSession(session_id=sid, user_id=uid, created_at=now, last_seen_at=now)
            for sid, (uid, _role) in self.sessions.items()
            if uid == user_id
        )

    def add(self, session_id: str, user_id: str, role: Role = Role.CLIENT) -> None:
        self.sessions[session_id] = (user_id, role)


@dataclass
class FakeAuditGateway:
    """Implements `gateways.AuditGateway`. Every call is recorded verbatim so a test can
    assert exactly what a privileged action reported to Audit, without needing a real Audit
    process or database."""

    calls: list[tuple] = field(default_factory=list)
    fail_next: bool = False

    async def record(
        self, operation: str, actor_user_id: str, *, target_user_id=None, reason=None,
        details=None,
    ) -> AuditOutcome:
        self.calls.append((operation, actor_user_id, target_user_id, reason, details))
        if self.fail_next:
            self.fail_next = False
            return AuditOutcome(recorded=False, error="UNKNOWN_ACTION", error_detail="fake failure")
        return AuditOutcome(recorded=True, event_id=f"evt_{len(self.calls)}")


@dataclass
class FakePersistenceGateway:
    """Implements `gateways.PersistenceGateway`. `ok` toggles whether the underlying call
    "succeeds", standing in for a real Persistence process once one exists."""

    ok: bool = True

    async def generate_export(self, user_id: str, provider_name: str, params_json: str = "{}"):
        from core.persistence.contracts import BlobRef

        if not self.ok:
            return ExportOutcome(ok=False, error="GENERATION_FAILED", error_detail="fake failure")
        return ExportOutcome(
            ok=True, export_blob_ref=BlobRef(f"blob_{user_id}"), export_id="exp_fake",
            generated_at=utcnow(),
        )

    async def erase_account(self, user_id: str):
        from core.account_guardian.contracts import EraseOutcome

        if not self.ok:
            return EraseOutcome(ok=False, error="GENERATION_FAILED", error_detail="fake failure")
        return EraseOutcome(ok=True, erased_at=utcnow())


@dataclass
class FakeBillingGateway:
    """Implements `gateways.BillingGateway`. `clear` toggles whether the fake subscription
    state is resolved — the concrete lever `test_deletion_request.py`'s billing-hold test
    needs (deep-dive §6.3, and this package's own §11-equivalent testing hook)."""

    clear: bool = True

    async def resolve_deletion_clearance(self, user_id: str) -> BillingClearance:
        return BillingClearance(clear=self.clear, detail="fake billing gateway")


@pytest.fixture
def session_gateway() -> FakeSessionGateway:
    return FakeSessionGateway()


@pytest.fixture
def audit_gateway() -> FakeAuditGateway:
    return FakeAuditGateway()


@pytest.fixture
def persistence_gateway() -> FakePersistenceGateway:
    return FakePersistenceGateway()


@pytest.fixture
def billing_gateway() -> FakeBillingGateway:
    return FakeBillingGateway()

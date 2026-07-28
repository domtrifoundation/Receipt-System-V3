"""Shared fixtures for Groups' unit tests.

**Every session lookup in this package's tests goes through `FakeSessionResolver`, never a
real Auth process.** `permission_gate.py`'s whole point is resolving the caller from a real
session rather than trusting anything the caller asserts — these fixtures are what makes that
distinction observable in a test: a "session" here is a plain dict a test wires up itself, and
`authorize_*` calls only ever see what was actually registered under a given `session_id`.

`run()` mirrors `tests/unit/core/audit/conftest.py`'s own helper rather than adding a
`pytest-asyncio` dependency this repo does not carry.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from core.auth.contracts import Role, Session
from core.groups.effective_group import EffectiveGroupResolver
from core.groups.membership import GroupMembershipService
from core.groups.permission_gate import PermissionGate
from core.groups.store import GroupsStore


def run(coro):
    """Drive one coroutine to completion. Each call gets its own loop, deliberately — a
    leaked loop between tests would make an ordering bug look like a flake."""
    return asyncio.run(coro)


def make_session(user_id: str, role: Role, session_id: str | None = None) -> Session:
    now = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)
    return Session(
        session_id=session_id or f"sess_{user_id}", user_id=user_id, role=role,
        created_at=now, last_seen_at=now, expires_at=now.replace(year=now.year + 1),
    )


class FakeSessionResolver:
    """A hand-populated stand-in for the real Auth-backed resolver.

    `resolve()` returns exactly what was registered for a `session_id` and nothing else —
    there is no fallback, no guessing, no "looks like an owner" heuristic. That is deliberate:
    a test wiring up `{"sess_owner": owner_session}` and then asking about `"sess_other"`
    must see `None`, the same as a real unresolvable session would.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def add(self, session: Session) -> Session:
        self._sessions[session.session_id] = session
        return session

    async def resolve(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)


class RaisingResolver:
    """A resolver that always raises — Auth unreachable, a real transport failure.

    Exists to prove `permission_gate.py`'s own `_resolve()` catches this rather than letting
    it escape: "cannot tell" must deny exactly like "resolved and forbidden" does
    (`docs/PRINCIPLES.md` §4.2), never crash the caller.
    """

    async def resolve(self, session_id: str) -> Session | None:
        raise ConnectionError("Auth is unreachable in this test")


@pytest.fixture
def store() -> GroupsStore:
    s = GroupsStore(":memory:")
    yield s
    s.close()


@pytest.fixture
def membership(store: GroupsStore) -> GroupMembershipService:
    return GroupMembershipService(store)


@pytest.fixture
def effective(store: GroupsStore) -> EffectiveGroupResolver:
    return EffectiveGroupResolver(store)


@pytest.fixture
def resolver() -> FakeSessionResolver:
    return FakeSessionResolver()


@pytest.fixture
def owner_session(resolver: FakeSessionResolver) -> Session:
    return resolver.add(make_session("owner_1", Role.OWNER))


@pytest.fixture
def staff_session(resolver: FakeSessionResolver) -> Session:
    return resolver.add(make_session("staff_1", Role.STAFF))


@pytest.fixture
def client_session(resolver: FakeSessionResolver) -> Session:
    return resolver.add(make_session("client_1", Role.CLIENT))


@pytest.fixture
def gate(resolver: FakeSessionResolver, store: GroupsStore) -> PermissionGate:
    return PermissionGate(resolver, store=store)

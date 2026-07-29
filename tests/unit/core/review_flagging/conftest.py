"""Shared fixtures for Review/Flagging's unit tests.

Every seam is a real Protocol implementation rather than a mock, because the guarantees under
test are all about what happens *between* this package and something else — an edit reaching
Persistence's real write path, a resolution reaching Audit, a high-stakes flag reaching
Notifications. A mock that recorded the call would confirm this package intended to reach out;
these fakes confirm what it actually handed over, which is the part that can be wrong.

The role resolver denies by default in production (`DenyAllSessions`), so a test that forgets
to wire one in fails closed exactly as a real process would.
"""

from __future__ import annotations

import asyncio

import pytest

from core.review_flagging.contracts import AuditRecordOutcome, EditWriteResult
from core.review_flagging.lifecycle import FlagStore


def run(coro):
    """Drive one coroutine to completion; one fresh loop per call.

    `asyncio.run` rather than `pytest-asyncio`, matching every other package's conftest here.
    A leaked loop between tests would make an ordering bug look like a flake.
    """
    return asyncio.run(coro)


class StaticRoles:
    """A session→role resolver over a fixed map.

    An unknown session resolves to `None`, which the gate must treat exactly as it treats an
    unreachable Auth: denied. Modelling both with one value is deliberate — a caller cannot
    tell them apart and neither should the decision.
    """

    def __init__(self, roles: dict[str, tuple[str, str]] | None = None) -> None:
        self._roles = roles or {}

    async def resolve(self, session_id: str):
        return self._roles.get(session_id)


class RecordingAudit:
    """Captures every audit record this package writes."""

    def __init__(self, *, fail: bool = False) -> None:
        self.records: list[dict] = []
        self._fail = fail

    async def record(
        self,
        operation: str,
        actor_user_id: str,
        *,
        target_user_id: str | None = None,
        reason: str | None = None,
        details: dict | None = None,
    ) -> AuditRecordOutcome:
        if self._fail:
            return AuditRecordOutcome(recorded=False, error_detail="audit sink unavailable")
        self.records.append(
            {
                "operation": operation,
                "actor_user_id": actor_user_id,
                "target_user_id": target_user_id,
                "reason": reason,
                "details": details or {},
            }
        )
        return AuditRecordOutcome(recorded=True, event_id=f"evt-{len(self.records)}")

    def operations(self) -> list[str]:
        return [r["operation"] for r in self.records]


class RecordingNotifier:
    """Captures which flags produced an immediate notification (§8's severity split)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.notified: list[str] = []
        self._fail = fail

    async def notify_new_flag(self, flag) -> bool:
        if self._fail:
            return False
        self.notified.append(flag.flag_type)
        return True


class RecordingWriteGateway:
    """Stands in for Persistence's normal write path.

    Records the full call — user, receipt, field, value, actor — because §7's edit hook is not
    "was something written" but "did it go through the *normal* path with the actor attached",
    and only the full argument set can show that.
    """

    def __init__(self, *, ok: bool = True) -> None:
        self.calls: list[tuple[str, str, str, str, str]] = []
        self._ok = ok

    async def apply_edit(
        self, user_id: str, receipt_id: str, field: str, new_value: str, actor_user_id: str
    ) -> EditWriteResult:
        self.calls.append((user_id, receipt_id, field, new_value, actor_user_id))
        if not self._ok:
            return EditWriteResult(ok=False, error_detail="persistence unavailable")
        # A real `historian_event_id` because that is exactly what §7's hook treats as proof
        # the write went through the normal, Historian-logged path rather than a shortcut.
        # A gateway returning `ok=True` with no event id would satisfy a weaker test while
        # describing precisely the bypass the hook exists to catch.
        return EditWriteResult(ok=True, historian_event_id=f"hist-{len(self.calls)}")


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit()


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def write_gateway() -> RecordingWriteGateway:
    return RecordingWriteGateway()


@pytest.fixture
def roles() -> StaticRoles:
    """Three real sessions: an owner, a staff member, a client, plus their user ids."""
    return StaticRoles(
        {
            "sess-owner": ("owner-1", "owner"),
            "sess-staff": ("staff-1", "staff"),
            "sess-staff-2": ("staff-2", "staff"),
            "sess-client": ("client-1", "client"),
        }
    )


@pytest.fixture
def store(tmp_path, roles, audit, notifier, write_gateway) -> FlagStore:
    created = FlagStore(
        tmp_path / "flags.sqlite",
        role_resolver=roles,
        audit=audit,
        notifier=notifier,
        edit_gateway=write_gateway,
    )
    yield created
    created.close()

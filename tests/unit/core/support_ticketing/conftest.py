"""Shared fixtures for Support Ticketing's unit tests.

The clock is injected because §9's auto-close window is fourteen days, and a test that waited
for it would not be a test. `FakeClock` also makes the case that actually matters expressible:
a reply on day 13 restarting the window, which is the whole reason the window exists and is
invisible to any test that only checks the boundary once.

Sessions resolve through a real map rather than a mock. The production default denies
(`deny_all_sessions`), so a test that forgot to wire one in fails closed exactly as a real
process would.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.support_ticketing.lifecycle import TicketStore

CLIENT_SESSION = "sess-client"
STAFF_SESSION = "sess-staff"
STAFF2_SESSION = "sess-staff-2"
OWNER_SESSION = "sess-owner"

#: Two distinct clients so cross-user isolation is testable, plus two staff so "one staff
#: member cannot take another's ticket" has two real people in it.
SESSIONS = {
    CLIENT_SESSION: ("client-1", "client"),
    "sess-other-client": ("client-2", "client"),
    STAFF_SESSION: ("staff-1", "staff"),
    STAFF2_SESSION: ("staff-2", "staff"),
    OWNER_SESSION: ("owner-1", "owner"),
}


class FakeClock:
    """A hand-advanced UTC clock, passed as the store's `now=` callable."""

    def __init__(self) -> None:
        self.now = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance_days(self, days: float) -> datetime:
        self.now = self.now + timedelta(days=days)
        return self.now


def resolve_session(session_id: str) -> tuple[str, str] | None:
    """A real resolver over `SESSIONS`; unknown sessions resolve to `None`, which denies."""
    return SESSIONS.get(session_id)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(clock: FakeClock) -> TicketStore:
    return TicketStore(sessions=resolve_session, now=clock)

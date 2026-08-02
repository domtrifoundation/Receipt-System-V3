"""Shared fixtures for the Audit API's unit tests.

**Why every fixture uses a real file rather than `":memory:"`**: this package deliberately
opens three *separate* connections under three different SQLite authorizer profiles — the
writer may insert, the query side may only read, the retention sweep is the only thing that
may delete. Two `":memory:"` connections are two unrelated databases, so an in-memory path
would silently give each of them its own empty store and every cross-module test would pass
for the wrong reason. A `tmp_path` file is what makes the profile separation observable.

`run()` exists instead of `pytest-asyncio` because this repo does not carry that dependency,
and adding one to the test tree for what `asyncio.run` already does would put a package in
`requirements.txt` and in `noxfile.py`'s deliberately narrow `FORWARD_COMPAT_DEPS` list for
no behavioural gain.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from core.audit.contracts import ActionType, AuditEvent
from core.audit.query import AuditQuery
from core.audit.writer import AuditWriter, new_event_id


def run(coro):
    """Drive one coroutine to completion. Each call gets its own loop, deliberately — a
    leaked loop between tests would make an ordering bug look like a flake."""
    return asyncio.run(coro)


def utc(days_ago: float = 0.0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def make_event(
    action_type: ActionType = ActionType.CONFIG_CHANGED,
    *,
    actor: str = "staff_1",
    days_ago: float = 0.0,
    **kwargs,
) -> AuditEvent:
    return AuditEvent(
        event_id=new_event_id(),
        action_type=action_type,
        actor_user_id=actor,
        occurred_at=utc(days_ago),
        **kwargs,
    )


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "audit.sqlite"


@pytest.fixture
def writer(db_path):
    w = AuditWriter(db_path)
    yield w
    w.close()


@pytest.fixture
def query(db_path):
    q = AuditQuery(db_path)
    yield q
    q.close()

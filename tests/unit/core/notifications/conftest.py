"""Shared fixtures and fakes for the Notifications/Inbox API's unit tests.

**Why every per-user store fixture uses a real file rather than `":memory:"`.** `InboxStore`
and `PreferenceStore` each cache one connection per user id they have touched (`inbox.py`,
`preferences.py`'s own docstrings). A `:memory:` path is per-connection, so two users would
silently share nothing at all *or* — worse, if the cache ever collapsed two users onto one
connection by mistake — silently share everything; a `tmp_path`-backed directory is what makes
per-user isolation an observable, testable property rather than an assumption.

`run()` exists instead of `pytest-asyncio` for the identical reason
`tests/unit/core/audit/conftest.py` states: this repo does not carry that dependency, and
`dispatch.Notifier.notify` is the only genuinely async surface in this package.

`FakeChannel` and `FakeRecipientResolver` are real test doubles, not partial reimplementations
of `channels/base.py`'s own Protocols — each one is exactly `OutboundChannel`/
`RecipientResolver`-shaped and nothing more, so a test exercising `dispatch.py` is exercising
the real fan-out and retry logic against a channel whose *outcome* is controlled, not against a
parallel notion of what a channel does.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from core.notifications.contracts import DeliveryOutcome, DeliveryStatus
from core.notifications.inbox import InboxStore
from core.notifications.preferences import PreferenceStore


def run(coro):
    """Drive one coroutine to completion. Each call gets its own loop, deliberately — a
    leaked loop between tests would make an ordering bug look like a flake (matches
    `tests/unit/core/audit/conftest.py::run`)."""
    return asyncio.run(coro)


@pytest.fixture
def top_level(tmp_path):
    return tmp_path / "top_level"


@pytest.fixture
def inbox(top_level):
    store = InboxStore(top_level)
    yield store
    store.close()


@pytest.fixture
def preferences(top_level):
    store = PreferenceStore(top_level)
    yield store
    store.close()


class FakeChannel:
    """An `OutboundChannel`-shaped test double whose `send()` outcome is scripted rather than
    computed — this is what lets `test_dispatch.py` assert the *retry policy* (attempt counts,
    escalation) independently of any real provider's own behaviour.

    `outcomes` is consumed one per attempt; once exhausted, the last outcome repeats — a test
    asserting "fails all three times" only has to supply one `FAILED` entry, not three.
    """

    def __init__(
        self,
        name: str = "email",
        *,
        configured: bool = True,
        outcomes: list[DeliveryStatus] | None = None,
    ) -> None:
        self._name = name
        self._configured = configured
        self._outcomes = list(outcomes) if outcomes else [
            DeliveryStatus(channel=name, outcome=DeliveryOutcome.SENT)
        ]
        self.send_calls: list[str] = []
        self.is_configured_calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def is_configured(self) -> bool:
        self.is_configured_calls += 1
        return self._configured

    async def send(self, user_id, notification, *, recipient):
        self.send_calls.append(recipient)
        index = min(len(self.send_calls) - 1, len(self._outcomes) - 1)
        return replace(self._outcomes[index], channel=self._name)


class ExplodingChannel:
    """An `OutboundChannel` whose `send()` raises — `dispatch.py`'s own contract is that this
    degrades to a `FAILED` attempt rather than escaping, and this double is what proves it."""

    name = "email"

    async def is_configured(self) -> bool:
        return True

    async def send(self, user_id, notification, *, recipient):
        raise RuntimeError("channel blew up")


class FakeRecipientResolver:
    """Resolves every user to the same fixed address, or to nothing if `address` is empty —
    the one lever `test_dispatch.py` needs to exercise "no recipient resolvable"."""

    def __init__(self, address: str | None = "user@example.com") -> None:
        self.address = address

    def resolve(self, user_id: str, channel: str) -> str | None:
        return self.address

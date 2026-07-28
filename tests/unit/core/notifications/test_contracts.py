"""Contract-shape tests for Notifications/Inbox API.

This package's own `contracts.py` docstring explains why none of today's contracts happen to
carry a dict-typed field — `Notification.reference` is a plain opaque string, not a mapping —
so the `forward_compat` test below asserts the property against this package's actual
`FrozenDict`-shaped constant, `errors.ERROR_SUMMARIES`/`ERROR_CODES`, the same way
`tests/unit/core/logs/test_contracts.py` asserts it against `LEVEL_STYLE_HINT`: the invariant
that matters is "this table is a `Mapping`, and code checking it must never test `dict`", not
which specific table happens to hold it.
"""

from __future__ import annotations

import collections.abc
from datetime import datetime, timedelta, timezone

import pytest

from common.frozen_dict import FrozenDict
from core.notifications.contracts import (
    ChannelPreference,
    DeliveryOutcome,
    DeliveryStatus,
    InboxQueryResult,
    KNOWN_CHANNELS,
    MarkReadResult,
    Notification,
    NotifyResult,
    PreferencesResult,
    utcnow,
)
from core.notifications.errors import ERROR_CODES, ERROR_SUMMARIES, InvalidNotification, code_for

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _notification(**over) -> Notification:
    base = dict(
        notification_id="ntf_1",
        user_id="user-1",
        category="run_complete",
        title="Run finished",
        body="Your run finished successfully.",
        created_at=NOW,
    )
    base.update(over)
    return Notification(**base)


@pytest.mark.forward_compat
def test_error_tables_are_mappings_not_dict_subclasses():
    """The §2.1.1 gotcha, asserted the way `core/logs/test_contracts.py` and
    `core/health/test_contracts.py` each assert it for their own module-level tables: on 3.15+
    the builtin `frozendict` is **not** a `dict` subclass, so `isinstance(x, dict)` silently
    takes the wrong branch against it."""
    assert isinstance(ERROR_SUMMARIES, collections.abc.Mapping)
    assert isinstance(ERROR_CODES, collections.abc.Mapping)
    assert isinstance(ERROR_SUMMARIES, type(FrozenDict({})))


def test_error_tables_reject_mutation():
    with pytest.raises(TypeError):
        ERROR_SUMMARIES["INVALID_NOTIFICATION"] = "changed"  # type: ignore[index]


def test_every_error_code_has_a_summary():
    """A code with no summary would leave a caller that only has the code with nothing to
    show — the same completeness `core/audit/errors.py::ERROR_SUMMARIES` guarantees for its
    own codes."""
    for code in ERROR_CODES.values():
        assert code in ERROR_SUMMARIES, code


def test_code_for_maps_the_internal_exception_hierarchy():
    assert code_for(InvalidNotification("x")) == "INVALID_NOTIFICATION"


def test_code_for_unmapped_exception_is_internal_not_a_crash():
    """`core/logs/errors.py::code_for`'s own reasoning: a caller getting `INTERNAL` with a
    real detail string is strictly better off than one getting a crash from the error path."""
    assert code_for(RuntimeError("unexpected")) == "INTERNAL"


def test_notification_is_frozen():
    notification = _notification()
    with pytest.raises(Exception):
        notification.title = "changed"  # type: ignore[misc]


def test_notification_is_read_reflects_read_at_not_a_separate_flag():
    unread = _notification()
    read = _notification(read_at=NOW + timedelta(minutes=5))
    assert not unread.is_read
    assert read.is_read


def test_notification_reference_is_a_reference_not_a_copy():
    """This package's own `CLAUDE.md` gotcha, made concrete: `reference` carries an id
    string, never a nested payload describing the referenced event."""
    notification = _notification(reference="break_glass_grant:bg_123")
    assert notification.reference == "break_glass_grant:bg_123"


def test_delivery_status_ok_only_for_sent():
    sent = DeliveryStatus(channel="email", outcome=DeliveryOutcome.SENT)
    failed = DeliveryStatus(channel="email", outcome=DeliveryOutcome.FAILED)
    skipped = DeliveryStatus(channel="email", outcome=DeliveryOutcome.SKIPPED_DISABLED)
    assert sent.ok
    assert not failed.ok
    assert not skipped.ok


def test_delivery_status_is_frozen():
    status = DeliveryStatus(channel="sms", outcome=DeliveryOutcome.SENT)
    with pytest.raises(Exception):
        status.outcome = DeliveryOutcome.FAILED  # type: ignore[misc]


def test_channel_preference_defaults_to_opted_out():
    """§5's own opt-in-not-opt-out guarantee, at the contract level: constructing a
    `ChannelPreference` with no explicit `enabled` must never come out `True`."""
    preference = ChannelPreference(user_id="user-1", channel="email")
    assert preference.enabled is False


def test_known_channels_is_a_closed_tuple():
    assert KNOWN_CHANNELS == ("email", "sms")
    assert isinstance(KNOWN_CHANNELS, tuple)


def test_result_ok_properties_reflect_error_code_emptiness():
    assert InboxQueryResult().ok
    assert not InboxQueryResult(error_code="INVALID_QUERY").ok
    assert PreferencesResult().ok
    assert not PreferencesResult(error_code="STORE_UNAVAILABLE").ok


def test_notify_result_ok_is_independent_of_channel_statuses():
    """§8's own resolved delivery-failure handling, at the contract level: `NotifyResult.ok`
    has no derivation from `channel_statuses` at all — it is a plain field the caller (in
    practice, only `dispatch.py`) sets once, from the in-app write's own outcome."""
    result = NotifyResult(
        ok=True,
        notification=_notification(),
        channel_statuses=(DeliveryStatus(channel="email", outcome=DeliveryOutcome.FAILED),),
    )
    assert result.ok
    assert not result.channel_statuses[0].ok


def test_mark_read_result_is_frozen():
    result = MarkReadResult(ok=True, notification_id="ntf_1")
    with pytest.raises(Exception):
        result.ok = False  # type: ignore[misc]


def test_utcnow_is_timezone_aware():
    assert utcnow().tzinfo is not None

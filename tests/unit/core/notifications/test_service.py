"""The gRPC servicer (`service.py`) — thin translation, and the one place identity resolution
is enforced (`docs/PRINCIPLES.md` §4.2).

The load-bearing property here is that **`QueryInbox`/`MarkRead`/`GetPreferences`/
`SetPreference` never trust a wire-supplied identity** — `notifications.proto` has no
`requesting_user_id` field at all (see the `.proto`'s own header comment), so the only way
these tests get a session recognised is by injecting a `session_resolver`, exactly mirroring
how a real deployment would resolve a session id from gRPC metadata against Auth.
"""

from __future__ import annotations

import asyncio

import pytest

from core.notifications.inbox import InboxStore
from core.notifications.preferences import PreferenceStore
from core.notifications.service import (
    NotificationsServicer,
    deny_all_sessions,
    session_id_from_context,
)

pb = pytest.importorskip(
    "core.notifications.generated.notifications_pb2",
    reason="grpcio/protobuf has no wheel on this interpreter yet (docs/MAINTENANCE.md §3)",
)


def run(coro):
    return asyncio.run(coro)


class FakeContext:
    """Stands in for `grpc.aio.ServicerContext`: only `invocation_metadata()` is ever used."""

    def __init__(self, session_id: str | None = None) -> None:
        self._session_id = session_id

    def invocation_metadata(self):
        if self._session_id is None:
            return ()
        return (("session_id", self._session_id),)


def _resolver_for(session_to_user: dict[str, str]):
    def resolver(context) -> str | None:
        session_id = session_id_from_context(context)
        return session_to_user.get(session_id) if session_id else None

    return resolver


@pytest.fixture
def servicer(top_level):
    inbox = InboxStore(top_level)
    preferences = PreferenceStore(top_level)
    resolver = _resolver_for({"sess-user-1": "user-1", "sess-staff-1": "staff-1"})
    return NotificationsServicer(inbox=inbox, preferences=preferences, session_resolver=resolver)


# ------------------------------------------------------------------------------ Notify


def test_notify_creates_an_in_app_notification_and_returns_it_on_the_wire(servicer):
    response = run(servicer.Notify(
        pb.NotifyRequest(user_id="user-1", category="run_complete", title="Done", body="ok"),
        None,
    ))

    assert response.ok
    assert response.notification.user_id == "user-1"
    assert response.notification.category == "run_complete"


def test_notify_is_never_gated_on_the_callers_own_session(servicer):
    """Notify is a system-to-system call naming its own recipient (deep-dive §1's own list of
    callers) — it must succeed with no session context at all."""
    response = run(servicer.Notify(
        pb.NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b"), None
    ))
    assert response.ok


# --------------------------------------------------------------------------- QueryInbox


def test_query_inbox_with_no_session_metadata_is_denied(servicer):
    """No `session_id` metadata at all is exactly the unauthenticated case — denied, not an
    empty-but-successful inbox."""
    run(servicer.Notify(
        pb.NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b"), None
    ))

    response = run(servicer.QueryInbox(pb.QueryInboxRequest(user_id="user-1"), FakeContext(None)))

    assert response.error_code == "CROSS_USER_ACCESS_DENIED"
    assert list(response.notifications) == []


def test_query_inbox_resolves_the_session_rather_than_trusting_the_request(servicer):
    """The request names `user_id="user-1"` and the session belongs to `user-1` — this must
    succeed, but *because* the resolved session matches, not because the request said so."""
    run(servicer.Notify(
        pb.NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b"), None
    ))

    response = run(servicer.QueryInbox(
        pb.QueryInboxRequest(user_id="user-1"), FakeContext("sess-user-1")
    ))

    assert response.error_code == ""
    assert len(response.notifications) == 1


def test_query_inbox_for_a_different_users_session_is_denied(servicer):
    """A resolved session for `staff-1` asking about `user-1`'s inbox is a cross-user read
    with no break-glass grant wired up — denied, the fail-closed default."""
    run(servicer.Notify(
        pb.NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b"), None
    ))

    response = run(servicer.QueryInbox(
        pb.QueryInboxRequest(user_id="user-1"), FakeContext("sess-staff-1")
    ))

    assert response.error_code == "CROSS_USER_ACCESS_DENIED"


def test_an_unrecognised_session_id_is_denied_not_treated_as_anonymous(servicer):
    response = run(servicer.QueryInbox(
        pb.QueryInboxRequest(user_id="user-1"), FakeContext("sess-does-not-exist")
    ))
    assert response.error_code == "CROSS_USER_ACCESS_DENIED"


# ----------------------------------------------------------------------------- MarkRead


def test_mark_read_resolves_identity_from_the_session_not_a_request_field(servicer):
    """`MarkReadRequest` carries no user id at all (see the `.proto`) — only a session can
    ever say whose notification this is."""
    notified = run(servicer.Notify(
        pb.NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b"), None
    ))

    response = run(servicer.MarkRead(
        pb.MarkReadRequest(notification_id=notified.notification.notification_id),
        FakeContext("sess-user-1"),
    ))

    assert response.ok


def test_mark_read_with_no_session_is_denied(servicer):
    response = run(servicer.MarkRead(pb.MarkReadRequest(notification_id="ntf_x"), FakeContext(None)))
    assert not response.ok
    assert response.error_code == "CROSS_USER_ACCESS_DENIED"


# -------------------------------------------------------------------------- preferences


def test_get_preferences_with_no_session_is_denied(servicer):
    response = run(servicer.GetPreferences(pb.GetPreferencesRequest(), FakeContext(None)))
    assert response.error_code == "SESSION_UNRESOLVABLE"


def test_set_preference_with_no_session_is_denied(servicer):
    response = run(servicer.SetPreference(
        pb.SetPreferenceRequest(channel="email", enabled=True), FakeContext(None)
    ))
    assert not response.ok
    assert response.error_code == "SESSION_UNRESOLVABLE"


def test_set_then_get_preferences_round_trip_through_the_wire(servicer):
    set_response = run(servicer.SetPreference(
        pb.SetPreferenceRequest(channel="email", enabled=True), FakeContext("sess-user-1")
    ))
    get_response = run(servicer.GetPreferences(pb.GetPreferencesRequest(), FakeContext("sess-user-1")))

    assert set_response.ok
    email_pref = next(p for p in get_response.preferences if p.channel == "email")
    assert email_pref.enabled is True


def test_preferences_are_always_the_sessions_own_never_a_named_subject(servicer):
    """There is no subject field on `SetPreferenceRequest`/`GetPreferencesRequest` at all
    (see the `.proto`) — this asserts that stays true against the generated descriptor, so a
    future field addition here would be caught rather than silently reopening a cross-user
    preference-setting path."""
    fields = {f.name for f in pb.SetPreferenceRequest.DESCRIPTOR.fields}
    assert "user_id" not in fields
    assert "requesting_user_id" not in fields


# ---------------------------------------------------------------------- default resolver


def test_deny_all_sessions_is_the_servicers_default(top_level):
    servicer = NotificationsServicer(inbox=InboxStore(top_level), preferences=PreferenceStore(top_level))
    try:
        response = run(servicer.QueryInbox(pb.QueryInboxRequest(user_id="user-1"), FakeContext("anything")))
        assert response.error_code == "CROSS_USER_ACCESS_DENIED"
    finally:
        servicer.close()


def test_session_id_from_context_handles_a_missing_context():
    assert session_id_from_context(None) is None


def test_deny_all_sessions_always_returns_none():
    assert deny_all_sessions(FakeContext("sess-user-1")) is None

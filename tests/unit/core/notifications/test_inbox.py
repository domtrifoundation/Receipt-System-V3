"""The in-app inbox: per-user isolation, the cross-user gate, and mark-read (§3, §4).

Two postures are tested here and they deliberately pull in opposite directions, mirroring
`tests/unit/core/logs/test_query.py`'s own split:

- **The identity/cross-user gate fails closed** (`docs/PRINCIPLES.md` §4.2) — an unresolvable
  caller, no checker wired up, and a checker that cannot be reached are all denials.
- **Category acceptance degrades gracefully** (§4.4) — an empty/blank category still gets
  recorded rather than losing the notification, since this is a labeling gap, not a security
  check.
"""

from __future__ import annotations

from core.notifications.contracts import InboxQuery, NotifyRequest
from core.notifications.errors import AccessCheckUnavailable
from core.notifications.inbox import AuthBreakGlassChecker, DenyCrossUser, InboxStore


def _notify(store: InboxStore, user_id: str, title: str = "hello", **over):
    return store.create(NotifyRequest(user_id=user_id, category="run_complete", title=title, body="b", **over))


# ------------------------------------------------------------------ per-user isolation


def test_a_user_sees_only_their_own_notifications(inbox):
    _notify(inbox, "user-1", title="for user 1")
    _notify(inbox, "user-2", title="for user 2")

    result = inbox.query(InboxQuery(user_id="user-1", requesting_user_id="user-1"))

    assert result.ok
    assert [n.title for n in result.notifications] == ["for user 1"]


def test_two_users_notifications_live_in_genuinely_separate_stores(inbox, top_level):
    """Not just filtered at read time — `db.py`'s own per-user file placement means user-2's
    notification is not even present in user-1's database file on disk."""
    _notify(inbox, "user-1", title="mine")
    _notify(inbox, "user-2", title="theirs")

    from core.notifications.db import connect, default_db_path

    conn = connect(default_db_path("user-1", top_level=top_level))
    rows = conn.execute("SELECT title FROM notifications").fetchall()
    conn.close()

    assert [r["title"] for r in rows] == ["mine"]


def test_newest_notification_is_returned_first(inbox):
    first = _notify(inbox, "user-1", title="first")
    second = _notify(inbox, "user-1", title="second")

    result = inbox.query(InboxQuery(user_id="user-1", requesting_user_id="user-1"))

    assert [n.notification_id for n in result.notifications] == [
        second.notification_id, first.notification_id,
    ]


def test_unread_only_filters_out_read_notifications(inbox):
    first = _notify(inbox, "user-1", title="one")
    _notify(inbox, "user-1", title="two")
    inbox.mark_read("user-1", first.notification_id)

    result = inbox.query(InboxQuery(user_id="user-1", requesting_user_id="user-1", unread_only=True))

    assert [n.title for n in result.notifications] == ["two"]


# ------------------------------------------------------------- unresolvable-session denial


def test_unresolvable_session_is_denied_not_defaulted_to_permitted(inbox):
    """`docs/PRINCIPLES.md` §4.2: a caller with no resolvable session is exactly the case a
    real gRPC deployment sees before Auth is reachable, and it must never read as anyone's
    inbox — not even an empty one silently returned as if authorized."""
    _notify(inbox, "user-1")

    result = inbox.query(InboxQuery(user_id="user-1", requesting_user_id=None))

    assert not result.ok
    assert result.error_code == "CROSS_USER_ACCESS_DENIED"
    assert result.notifications == ()


def test_cross_user_read_is_denied_by_default(inbox):
    """The identical fail-closed default `core/logs/query.py::DenyCrossUser` uses: a process
    running before Auth is reachable serves nothing cross-user, which is correct, not
    degraded."""
    _notify(inbox, "user-2")

    result = inbox.query(InboxQuery(user_id="user-2", requesting_user_id="staff-1"))

    assert not result.ok
    assert result.error_code == "CROSS_USER_ACCESS_DENIED"


def test_an_active_break_glass_grant_allows_the_cross_user_read(inbox):
    _notify(inbox, "user-2", title="client's own notification")
    checker = AuthBreakGlassChecker(lambda requester, subject: requester == "staff-1")
    gated = InboxStore(inbox._top_level, checker=checker)  # noqa: SLF001 - reuse the same files

    result = gated.query(InboxQuery(user_id="user-2", requesting_user_id="staff-1"))

    assert result.ok
    assert [n.title for n in result.notifications] == ["client's own notification"]
    gated.close()


def test_an_unreachable_auth_denies_rather_than_permits(inbox):
    """§4.2 exactly: a security check that cannot be evaluated means unsafe, never a silent
    bypass — mirrors `tests/unit/core/logs/test_query.py`'s identical case for Logs' own
    break-glass adapter."""

    def _explode(requester, subject):
        raise ConnectionError("auth unreachable")

    gated = InboxStore(inbox._top_level, checker=AuthBreakGlassChecker(_explode))  # noqa: SLF001

    result = gated.query(InboxQuery(user_id="user-2", requesting_user_id="staff-1"))

    assert result.error_code == "ACCESS_CHECK_UNAVAILABLE"
    gated.close()


def test_denials_are_data_not_exceptions(inbox):
    """`docs/PRINCIPLES.md` §4.1 — a caller checks `.error_code`, nothing here raises."""
    result = inbox.query(InboxQuery(user_id="user-2", requesting_user_id="user-1"))
    assert isinstance(result.error_detail, str) and result.error_detail


def test_own_user_read_never_needs_a_checker_at_all(inbox):
    """The default `DenyCrossUser` only denies *cross*-user reads; an own-user read must keep
    working even with no checker wired up (`inbox.authorize`'s own short-circuit)."""
    _notify(inbox, "user-1")
    result = inbox.query(InboxQuery(user_id="user-1", requesting_user_id="user-1"))
    assert result.ok


def test_deny_cross_user_is_the_default_checker_type(top_level):
    assert isinstance(InboxStore(top_level)._checker, DenyCrossUser)  # noqa: SLF001


def test_access_check_unavailable_is_a_real_internal_type():
    assert issubclass(AccessCheckUnavailable, Exception)


# ------------------------------------------------------------------------- mark-read


def test_mark_read_only_touches_the_requesters_own_notification(inbox):
    other = _notify(inbox, "user-2", title="not yours")

    result = inbox.mark_read("user-1", other.notification_id)

    assert not result.ok
    assert result.error_code == "NOTIFICATION_NOT_FOUND"


def test_mark_read_with_no_resolvable_caller_is_denied(inbox):
    notification = _notify(inbox, "user-1")

    result = inbox.mark_read(None, notification.notification_id)

    assert not result.ok
    assert result.error_code == "CROSS_USER_ACCESS_DENIED"


def test_mark_read_round_trips_into_the_query_result(inbox):
    notification = _notify(inbox, "user-1")

    marked = inbox.mark_read("user-1", notification.notification_id)
    result = inbox.query(InboxQuery(user_id="user-1", requesting_user_id="user-1"))

    assert marked.ok
    assert result.notifications[0].read_at is not None


# ------------------------------------------------------------------------ write path


def test_create_requires_a_user_id(top_level):
    from core.notifications.errors import InvalidNotification

    store = InboxStore(top_level)
    try:
        raised = False
        try:
            store.create(NotifyRequest(user_id="", category="x", title="t", body="b"))
        except InvalidNotification:
            raised = True
        assert raised
    finally:
        store.close()


def test_unrecognised_category_still_gets_recorded(top_level):
    """§4.4: category acceptance is not a security check, so a blank category degrades to a
    fallback label rather than losing the notification."""
    store = InboxStore(top_level)
    try:
        notification = store.create(NotifyRequest(user_id="user-1", category="", title="t", body="b"))
        assert notification.category == "uncategorized"
    finally:
        store.close()


def test_metrics_count_creates_reads_and_denials(inbox):
    _notify(inbox, "user-1")
    inbox.query(InboxQuery(user_id="user-1", requesting_user_id="user-1"))
    inbox.query(InboxQuery(user_id="user-1", requesting_user_id="staff-1"))

    snapshot = inbox.metrics.snapshot()
    assert snapshot.notifications_created == 1
    assert snapshot.inbox_reads_served == 1
    assert snapshot.inbox_reads_denied == 1

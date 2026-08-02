"""Session lifecycle: issuance, the raising validation path, and instant revocation."""

from __future__ import annotations

from datetime import timedelta

import pytest

from core.auth.contracts import Role, utcnow
from core.auth.errors import SessionExpired, SessionInvalid
from core.auth.session.session_store import SessionStore

from ..conftest import run


@pytest.fixture
def sessions(db):
    return SessionStore(db, ttl_hours=720)


def test_issued_session_carries_a_csrf_token_and_an_opaque_id(sessions):
    issued = run(sessions.create("u_1", Role.CLIENT))
    assert issued.csrf_token and issued.csrf_token != issued.session.session_id
    # High-entropy and not derived from the user id — a guessable session id is a forgeable
    # session (deep-dive §3).
    assert len(issued.session.session_id) >= 32
    assert "u_1" not in issued.session.session_id


def test_role_is_snapshotted_at_creation(sessions, directory, client_user):
    issued = run(sessions.create(client_user.user_id, Role.CLIENT))
    directory.set_role(client_user.user_id, Role.STAFF)
    # The live session still reports the old role — which is precisely why every role change
    # must revoke sessions (§5.3, enforced in roles/role_check.py).
    assert run(sessions.get(issued.session.session_id)).role is Role.CLIENT


def test_validate_raises_rather_than_returning_an_error(sessions):
    with pytest.raises(SessionInvalid):
        run(sessions.validate("no-such-session"))


def test_revocation_takes_effect_on_the_very_next_call(sessions):
    issued = run(sessions.create("u_1", Role.OWNER))
    assert run(sessions.validate(issued.session.session_id)).user_id == "u_1"
    assert run(sessions.revoke(issued.session.session_id))
    with pytest.raises(SessionInvalid):
        run(sessions.validate(issued.session.session_id))
    # A second revocation is a no-op, not an error.
    assert not run(sessions.revoke(issued.session.session_id))


def test_expired_session_raises_expired_not_invalid(db):
    store = SessionStore(db, ttl_hours=720)
    issued = run(store.create("u_1", Role.CLIENT))
    db.write(
        "UPDATE sessions SET expires_at = ? WHERE session_id = ?",
        ((utcnow() - timedelta(seconds=1)).isoformat(), issued.session.session_id),
    )
    with pytest.raises(SessionExpired):
        run(store.validate(issued.session.session_id))


def test_revoke_all_for_user_kills_every_live_session(sessions):
    first = run(sessions.create("u_1", Role.STAFF))
    second = run(sessions.create("u_1", Role.STAFF))
    other = run(sessions.create("u_2", Role.CLIENT))
    assert run(sessions.revoke_all_for_user("u_1")) == 2
    for issued in (first, second):
        with pytest.raises(SessionInvalid):
            run(sessions.validate(issued.session.session_id))
    assert run(sessions.validate(other.session.session_id)).user_id == "u_2"


def test_touch_advances_last_seen_without_extending_expiry(sessions):
    issued = run(sessions.create("u_1", Role.CLIENT))
    run(sessions.touch(issued.session.session_id))
    refreshed = run(sessions.get(issued.session.session_id))
    assert refreshed.last_seen_at >= issued.session.last_seen_at
    assert refreshed.expires_at == issued.session.expires_at


def test_expiry_never_depends_on_the_cleanup_sweep(db):
    """The sweep is housekeeping. Validation must already refuse an expired session before
    it has ever run — otherwise a wedged background job silently extends every session."""
    store = SessionStore(db, ttl_hours=720)
    issued = run(store.create("u_1", Role.CLIENT))
    db.write(
        "UPDATE sessions SET expires_at = ? WHERE session_id = ?",
        ((utcnow() - timedelta(minutes=1)).isoformat(), issued.session.session_id),
    )
    with pytest.raises(SessionExpired):
        run(store.validate(issued.session.session_id))
    assert store.purge_expired_sync() == 1


def test_hot_path_lookup_uses_an_index_not_a_scan(sessions):
    """§11's session-store hook, asserted directly against the query plan rather than
    inferred from a timing run — `ValidateSession` is on every request in the system."""
    plan = " ".join(sessions.lookup_plan()).upper()
    assert "SCAN" not in plan
    assert "SEARCH" in plan and "SESSIONS" in plan


def test_step_up_marking_is_a_server_side_timestamp(sessions):
    issued = run(sessions.create("u_1", Role.OWNER))
    assert run(sessions.get(issued.session.session_id)).step_up_at is None
    run(sessions.mark_step_up(issued.session.session_id))
    assert run(sessions.get(issued.session.session_id)).step_up_at is not None

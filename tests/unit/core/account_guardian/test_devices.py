"""Device/session management (`devices.py`, deep-dive §4).

The property this file exists to prove above all others: **one user cannot revoke another
user's session by knowing or guessing its id.** Every other test here is secondary to that
one.
"""

from __future__ import annotations

from core.account_guardian import devices
from core.account_guardian.errors import E_CAPABILITY_MISSING, E_DEPENDENCY_UNAVAILABLE, E_NOT_FOUND, E_OWNERSHIP_DENIED

from .conftest import run


def test_one_user_cannot_revoke_anothers_session(session_gateway, audit_gateway):
    """The core guarantee. `user_b` must never be able to end `user_a`'s session, even
    though nothing about the wire request prevents `user_b` from naming it."""
    session_gateway.add("sess_a", "user_a")
    session_gateway.add("sess_b", "user_b")

    result = run(devices.revoke_device(session_gateway, audit_gateway, "user_b", "sess_a"))

    assert result.error == E_OWNERSHIP_DENIED
    assert not result.revoked
    assert "sess_a" in session_gateway.sessions, "the session must still exist — untouched"
    assert audit_gateway.calls == [], "a denied action must not be recorded as if it happened"


def test_a_user_can_revoke_their_own_other_device(session_gateway, audit_gateway):
    session_gateway.add("sess_a_phone", "user_a")
    session_gateway.add("sess_a_laptop", "user_a")

    result = run(devices.revoke_device(session_gateway, audit_gateway, "user_a", "sess_a_phone"))

    assert result.revoked
    assert result.sessions_revoked == 1
    assert "sess_a_phone" not in session_gateway.sessions
    assert "sess_a_laptop" in session_gateway.sessions, "revoking one device must not touch another"


def test_revoking_a_session_that_does_not_exist_is_not_found_not_a_crash(session_gateway, audit_gateway):
    result = run(devices.revoke_device(session_gateway, audit_gateway, "user_a", "sess_ghost"))
    assert result.error == E_NOT_FOUND
    assert not result.revoked


def test_every_revocation_produces_an_audit_entry(session_gateway, audit_gateway):
    session_gateway.add("sess_a", "user_a")

    result = run(devices.revoke_device(session_gateway, audit_gateway, "user_a", "sess_a"))

    assert result.audit_recorded
    assert len(audit_gateway.calls) == 1
    operation, actor, target, reason, details = audit_gateway.calls[0]
    assert operation == "account_guardian_device_revoked"
    assert actor == "user_a"
    assert target == "user_a"
    assert details["session_id"] == "sess_a"


def test_a_degraded_audit_write_is_surfaced_not_swallowed(session_gateway, audit_gateway):
    """The revocation itself can succeed while Audit's own write degrades — the two must
    stay tellable apart (`docs/PRINCIPLES.md` §4.2, §4.4), never silently merged into one
    "it worked" result."""
    session_gateway.add("sess_a", "user_a")
    audit_gateway.fail_next = True

    result = run(devices.revoke_device(session_gateway, audit_gateway, "user_a", "sess_a"))

    assert result.revoked, "the revocation itself still happened"
    assert not result.audit_recorded
    assert result.audit_error


def test_revoke_all_devices_is_always_scoped_to_the_callers_own_user_id(session_gateway, audit_gateway):
    session_gateway.add("sess_a1", "user_a")
    session_gateway.add("sess_a2", "user_a")
    session_gateway.add("sess_b1", "user_b")

    result = run(devices.revoke_all_devices(session_gateway, audit_gateway, "user_a"))

    assert result.sessions_revoked == 2
    assert "sess_b1" in session_gateway.sessions, "another user's session must be untouched"


def test_list_sessions_marks_is_current_correctly(session_gateway):
    session_gateway.add("sess_a1", "user_a")
    session_gateway.add("sess_a2", "user_a")

    result = run(devices.list_sessions(session_gateway, "user_a", current_session_id="sess_a2"))

    by_id = {d.session_id: d for d in result.devices}
    assert by_id["sess_a1"].is_current is False
    assert by_id["sess_a2"].is_current is True


def test_list_sessions_never_returns_another_users_devices(session_gateway):
    session_gateway.add("sess_a", "user_a")
    session_gateway.add("sess_b", "user_b")

    result = run(devices.list_sessions(session_gateway, "user_a"))

    assert {d.session_id for d in result.devices} == {"sess_a"}


def test_list_sessions_degrades_when_auth_has_no_listing_capability(session_gateway):
    """The real, documented gap (`gateways.py`): `GrpcSessionGateway.list_sessions` always
    raises `CapabilityMissing` today, because Auth's own `auth.proto` has no RPC for this.
    This test proves the degradation path, not the (currently nonexistent) real RPC."""
    from core.account_guardian.gateways import GrpcSessionGateway

    real_shaped_gateway = GrpcSessionGateway()

    result = run(devices.list_sessions(real_shaped_gateway, "user_a"))

    assert result.devices == ()
    assert result.error == E_CAPABILITY_MISSING


def test_revoke_surfaces_a_transport_failure_rather_than_a_silent_no_op(session_gateway, audit_gateway):
    """Deep-dive §11's own named testing hook: a revocation during Auth being briefly
    unavailable must be a visible failure, never a silent no-op the caller reads as
    "the device was logged out" when it was not."""
    session_gateway.add("sess_a", "user_a")
    session_gateway.unavailable = True

    result = run(devices.revoke_device(session_gateway, audit_gateway, "user_a", "sess_a"))

    assert result.error == E_DEPENDENCY_UNAVAILABLE
    assert not result.revoked

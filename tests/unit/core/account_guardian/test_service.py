"""The `AccountGuardianServicer` gRPC surface (`service.py`) — the layer where Auth's own
raise-loudly carve-out actually crosses into this package's boundary.

Exercises the servicer's methods directly against injected fakes (`conftest.py`), the same
"prove the real behaviour without a live server" approach `core/health/`'s own service tests
use. Every RPC that carries a `session_id` must abort `UNAUTHENTICATED` on an unresolvable
one — that is Auth's carve-out, reused rather than swallowed into a data field
(`docs/PRINCIPLES.md` §4.1) — and every staff-only recovery RPC must abort `PERMISSION_DENIED`
for a client-role caller, never quietly allow it.
"""

from __future__ import annotations

import grpc
import pytest

from core.account_guardian.contracts import Role
from core.account_guardian.service import AccountGuardianServicer

from .conftest import Aborted, run


@pytest.fixture
def servicer(db, session_gateway, audit_gateway, persistence_gateway, billing_gateway):
    return AccountGuardianServicer(
        session_gateway=session_gateway, audit_gateway=audit_gateway,
        persistence_gateway=persistence_gateway, billing_gateway=billing_gateway, db=db,
    )


class _Req:
    """A tiny stand-in for a generated protobuf request message — plain attribute access is
    all `service.py` ever needs from one."""

    def __init__(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)


# --------------------------------------------------------------- fail-closed on bad sessions


@pytest.mark.parametrize(
    "method_name, extra_fields",
    [
        ("ListSessions", {}),
        ("RevokeSession", {"target_session_id": "sess_x"}),
        ("RevokeAllSessions", {}),
        ("RequestSsoLink", {"provider": "google", "step_up_confirmed": True}),
        ("RequestDataExport", {"provider_name": ""}),
        ("RequestDeletion", {"grace_period_days": 0}),
    ],
)
def test_every_session_carrying_rpc_aborts_unauthenticated_on_an_unresolvable_session(
    servicer, context, method_name, extra_fields
):
    """Fail-closed, and raised — never a data field a caller could forget to check
    (`docs/PRINCIPLES.md` §4.1, §4.2). This is the property every RPC below shares, proved
    once per RPC rather than assumed from one example."""
    request = _Req(session_id="no-such-session", **extra_fields)
    method = getattr(servicer, method_name)

    with pytest.raises(Aborted) as excinfo:
        run(method(request, context))

    assert excinfo.value.code == grpc.StatusCode.UNAUTHENTICATED


# ------------------------------------------------------------------------- devices via wire


def test_revoke_session_denies_ownership_as_data_not_an_abort(servicer, context, session_gateway):
    session_gateway.add("sess_a", "user_a")
    session_gateway.add("sess_b", "user_b")

    response = run(servicer.RevokeSession(
        _Req(session_id="sess_b", target_session_id="sess_a"), context
    ))

    assert response.error_code == "OWNERSHIP_DENIED"
    assert not response.revoked


def test_revoke_session_end_to_end_produces_an_audit_entry(servicer, context, session_gateway, audit_gateway):
    session_gateway.add("sess_a", "user_a")

    response = run(servicer.RevokeSession(
        _Req(session_id="sess_a", target_session_id="sess_a"), context
    ))

    assert response.revoked
    assert response.audit_recorded
    assert len(audit_gateway.calls) == 1


def test_list_sessions_only_returns_the_callers_own_devices(servicer, context, session_gateway):
    session_gateway.add("sess_a", "user_a")
    session_gateway.add("sess_b", "user_b")

    response = run(servicer.ListSessions(_Req(session_id="sess_a"), context))

    assert [d.session_id for d in response.devices] == ["sess_a"]


# ------------------------------------------------------------------ recovery: staff-only gate


def test_approve_recovery_is_refused_to_a_client_role_caller(servicer, context, session_gateway):
    """Fail-closed on role, exactly like Gateway's own owner/staff route enforcement
    (Auth deep-dive §6.1) — a client role approving their own (or anyone's) recovery case
    would defeat the entire "staff-mediated, not self-service" design (deep-dive §5)."""
    session_gateway.add("sess_client", "user_a", role=Role.CLIENT)
    created = run(servicer.RequestAccountRecovery(_Req(user_id="user_a", lost_method=""), context))

    with pytest.raises(Aborted) as excinfo:
        run(servicer.ApproveRecovery(
            _Req(request_id=created.request_id, session_id="sess_client", reason="trust me"),
            context,
        ))

    assert excinfo.value.code == grpc.StatusCode.PERMISSION_DENIED


def test_approve_recovery_succeeds_for_a_staff_session_after_checklist_and_is_audited(
    servicer, context, session_gateway, audit_gateway
):
    session_gateway.add("sess_staff", "staff_1", role=Role.STAFF)
    created = run(servicer.RequestAccountRecovery(_Req(user_id="user_a", lost_method="passkey"), context))
    run(servicer.UpdateRecoveryChecklist(_Req(
        request_id=created.request_id, session_id="sess_staff", knowledge_check_passed=True,
        knowledge_check_note="matched a recent receipt", recovery_contact_state=0,
        vouched_by_user_id="",
    ), context))

    response = run(servicer.ApproveRecovery(
        _Req(request_id=created.request_id, session_id="sess_staff", reason="verified"), context
    ))

    assert response.stage == "approved"
    assert response.audit_recorded
    assert any(call[0] == "account_recovery_approve" for call in audit_gateway.calls)


def test_request_account_recovery_needs_no_session_at_all(servicer, context):
    """Deep-dive §5: a user filing this may have lost every authentication method they had
    — the one RPC in this service reachable with no valid session."""
    response = run(servicer.RequestAccountRecovery(_Req(user_id="user_a", lost_method=""), context))

    assert response.stage == "requested"
    assert response.error_code == ""


def test_request_account_recovery_rejects_an_unrecognised_lost_method(servicer, context):
    response = run(servicer.RequestAccountRecovery(_Req(user_id="user_a", lost_method="not-a-method"), context))
    assert response.error_code == "INVALID_REQUEST"


# ------------------------------------------------------------------------------- deletion


def test_request_deletion_billing_hold_end_to_end(servicer, context, session_gateway, billing_gateway):
    session_gateway.add("sess_a", "user_a")
    billing_gateway.clear = False

    response = run(servicer.RequestDeletion(
        _Req(session_id="sess_a", grace_period_days=0), context
    ))

    assert response.stage == "billing_hold"
    assert response.grace_period_ends_at_unix == 0


def test_cancel_deletion_denies_ownership_as_data(servicer, context, session_gateway):
    session_gateway.add("sess_a", "user_a")
    created = run(servicer.RequestDeletion(_Req(session_id="sess_a", grace_period_days=0), context))

    response = run(servicer.CancelDeletion(
        _Req(request_id=created.request_id, acting_user_id="user_b"), context
    ))

    assert response.error_code == "OWNERSHIP_DENIED"


# -------------------------------------------------------------------------------- consent


def test_consent_round_trip_through_the_wire(servicer, context, db):
    from core.account_guardian import consent as consent_module
    from core.account_guardian.contracts import ConsentDocumentType

    run(consent_module.publish_version(
        db, ConsentDocumentType.TERMS_OF_SERVICE, "v1", "config/tos_v1.md", requires_reconsent=True
    ))

    version_response = run(servicer.GetCurrentPolicyVersion(
        _Req(document_type="terms_of_service"), context
    ))
    assert version_response.published
    assert version_response.version == "v1"

    before = run(servicer.RecordConsent(_Req(
        user_id="user_a", document_type="terms_of_service", document_version="v1", ip_address="",
    ), context))
    assert before.has_valid_consent

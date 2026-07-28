"""Right to erasure — the grace-period lifecycle (`privacy/deletion_request.py`, deep-dive
§6.3).

Every stage transition the deep-dive names is asserted explicitly here, including the two
it calls out as the concrete validation of its own cross-API contract: a request against an
account with an active subscription enters `BILLING_HOLD` rather than proceeding, and
resumes once Billing reports clean resolution.
"""

from __future__ import annotations

from datetime import timedelta

from core.account_guardian.contracts import DeletionStage
from core.account_guardian.errors import E_ALREADY_RESOLVED, E_INVALID_STAGE_TRANSITION, E_NOT_FOUND, E_OWNERSHIP_DENIED

from ..conftest import run, utcnow


def test_a_clean_billing_state_enters_grace_period_immediately(db, audit_gateway, billing_gateway):
    billing_gateway.clear = True

    result = run(deletion_request_module().request_deletion(db, audit_gateway, billing_gateway, "user_a"))

    assert result.request.stage is DeletionStage.GRACE_PERIOD
    assert result.request.grace_period_ends_at is not None
    assert result.audit_recorded


def test_an_unresolved_subscription_enters_billing_hold_not_grace_period(db, audit_gateway, billing_gateway):
    """The concrete cross-API contract validation the deep-dive names explicitly (§6.3,
    §11): never proceed past billing state silently."""
    billing_gateway.clear = False

    result = run(deletion_request_module().request_deletion(db, audit_gateway, billing_gateway, "user_a"))

    assert result.request.stage is DeletionStage.BILLING_HOLD
    assert result.request.grace_period_ends_at is None


def test_billing_hold_resumes_toward_grace_period_once_billing_clears(db, audit_gateway, billing_gateway, persistence_gateway):
    dr = deletion_request_module()
    billing_gateway.clear = False
    held = run(dr.request_deletion(db, audit_gateway, billing_gateway, "user_a")).request
    assert held.stage is DeletionStage.BILLING_HOLD

    billing_gateway.clear = True
    resumed = run(dr.advance(db, audit_gateway, persistence_gateway, billing_gateway, held.request_id))

    assert resumed.request.stage is DeletionStage.GRACE_PERIOD
    assert resumed.request.grace_period_ends_at is not None


def test_only_one_active_deletion_request_exists_per_user_at_a_time(db, audit_gateway, billing_gateway):
    dr = deletion_request_module()
    run(dr.request_deletion(db, audit_gateway, billing_gateway, "user_a"))

    second = run(dr.request_deletion(db, audit_gateway, billing_gateway, "user_a"))

    assert second.error == E_ALREADY_RESOLVED


def test_a_new_request_is_allowed_after_the_previous_one_is_cancelled(db, audit_gateway, billing_gateway):
    dr = deletion_request_module()
    first = run(dr.request_deletion(db, audit_gateway, billing_gateway, "user_a")).request
    run(dr.cancel_deletion(db, audit_gateway, first.request_id, "user_a"))

    second = run(dr.request_deletion(db, audit_gateway, billing_gateway, "user_a"))

    assert second.error is None
    assert second.request.stage is DeletionStage.GRACE_PERIOD


def test_one_user_cannot_cancel_anothers_deletion_request(db, audit_gateway, billing_gateway):
    dr = deletion_request_module()
    request = run(dr.request_deletion(db, audit_gateway, billing_gateway, "user_a")).request

    result = run(dr.cancel_deletion(db, audit_gateway, request.request_id, "user_b"))

    assert result.error == E_OWNERSHIP_DENIED
    unchanged = run(dr.get(db, request.request_id))
    assert unchanged.stage is DeletionStage.GRACE_PERIOD


def test_cancellation_correctly_fails_once_processing_has_started(db, audit_gateway, billing_gateway, persistence_gateway):
    """Deep-dive §6.3, stated precisely: "once PROCESSING has begun, it's genuinely
    irreversible and this call correctly fails rather than pretending to succeed." — proved
    here by driving a request all the way to PROCESSING and then trying to cancel it."""
    dr = deletion_request_module()
    request = run(dr.request_deletion(db, audit_gateway, billing_gateway, "user_a")).request
    future = utcnow() + timedelta(days=dr.DEFAULT_GRACE_PERIOD_DAYS + 1)
    # Force a failing erasure so the request stays parked in PROCESSING rather than racing
    # straight through to COMPLETE, so the cancel attempt below genuinely targets PROCESSING.
    persistence_gateway.ok = False
    run(dr.advance(db, audit_gateway, persistence_gateway, billing_gateway, request.request_id, now=future))
    mid_flight = run(dr.get(db, request.request_id))
    assert mid_flight.stage is DeletionStage.PROCESSING

    result = run(dr.cancel_deletion(db, audit_gateway, request.request_id, "user_a"))

    assert result.error == E_INVALID_STAGE_TRANSITION


def test_grace_period_elapsing_with_clean_billing_advances_all_the_way_to_complete(db, audit_gateway, billing_gateway, persistence_gateway):
    dr = deletion_request_module()
    request = run(dr.request_deletion(db, audit_gateway, billing_gateway, "user_a")).request
    future = utcnow() + timedelta(days=dr.DEFAULT_GRACE_PERIOD_DAYS + 1)

    result = run(dr.advance(db, audit_gateway, persistence_gateway, billing_gateway, request.request_id, now=future))

    assert result.request.stage is DeletionStage.COMPLETE
    assert result.request.completed_at is not None


def test_advance_before_the_grace_period_elapses_is_a_no_op(db, audit_gateway, billing_gateway, persistence_gateway):
    dr = deletion_request_module()
    request = run(dr.request_deletion(db, audit_gateway, billing_gateway, "user_a")).request

    soon = utcnow() + timedelta(days=1)
    result = run(dr.advance(db, audit_gateway, persistence_gateway, billing_gateway, request.request_id, now=soon))

    assert result.request.stage is DeletionStage.GRACE_PERIOD, "not due yet — must not jump ahead"


def test_advance_on_an_unknown_request_is_not_found(db, audit_gateway, billing_gateway, persistence_gateway):
    dr = deletion_request_module()
    result = run(dr.advance(db, audit_gateway, persistence_gateway, billing_gateway, "del_ghost"))
    assert result.error == E_NOT_FOUND


def test_completed_deletion_is_recorded_as_a_distinct_audit_operation(db, audit_gateway, billing_gateway, persistence_gateway):
    dr = deletion_request_module()
    request = run(dr.request_deletion(db, audit_gateway, billing_gateway, "user_a")).request
    future = utcnow() + timedelta(days=dr.DEFAULT_GRACE_PERIOD_DAYS + 1)
    audit_gateway.calls.clear()

    run(dr.advance(db, audit_gateway, persistence_gateway, billing_gateway, request.request_id, now=future))

    operations = [call[0] for call in audit_gateway.calls]
    assert "account_guardian_deletion_completed" in operations


def deletion_request_module():
    from core.account_guardian.privacy import deletion_request

    return deletion_request

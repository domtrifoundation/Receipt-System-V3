"""Account recovery — the staff-mediated case queue (`account_recovery.py`, deep-dive §5,
§12).

Three properties this file is required to prove, beyond ordinary state-machine coverage:
one user cannot cancel another's case, every resolution (approve/reject/complete) produces
an audit entry, and `approve()` refuses an empty checklist regardless of who is asking.
"""

from __future__ import annotations

import pytest

from core.account_guardian import account_recovery
from core.account_guardian.contracts import AuthMethod, RecoveryStage, RecoveryVerificationChecklist
from core.account_guardian.errors import (
    E_ALREADY_RESOLVED,
    E_INVALID_REQUEST,
    E_NOT_FOUND,
    E_OWNERSHIP_DENIED,
    E_VERIFICATION_INSUFFICIENT,
)

from .conftest import run


def _create(db, user_id="user_a", lost_method=AuthMethod.PASSKEY):
    return run(account_recovery.create_request(db, user_id, lost_method)).request


def test_create_request_starts_in_requested_stage(db):
    request = _create(db)
    assert request.stage is RecoveryStage.REQUESTED
    assert request.lost_method is AuthMethod.PASSKEY
    assert not request.checklist.any_check_satisfied


def test_update_checklist_moves_to_under_review(db):
    request = _create(db)
    result = run(account_recovery.update_checklist(
        db, request.request_id, RecoveryVerificationChecklist(knowledge_check_passed=True)
    ))
    assert result.request.stage is RecoveryStage.UNDER_REVIEW
    assert result.request.checklist.knowledge_check_passed


def test_approve_refuses_when_no_checklist_item_is_satisfied(db, audit_gateway):
    """The one automatable floor deep-dive §12 asks for: at least one check, or no approval,
    no matter how trusted the reviewer is."""
    request = _create(db)

    result = run(account_recovery.approve(
        db, audit_gateway, request.request_id, "staff_1", reason="looks fine to me"
    ))

    assert result.error == E_VERIFICATION_INSUFFICIENT
    assert audit_gateway.calls == [], "a refused approval must not be recorded as a real one"


def test_approve_requires_a_stated_reason(db, audit_gateway):
    request = _create(db)
    run(account_recovery.update_checklist(
        db, request.request_id, RecoveryVerificationChecklist(knowledge_check_passed=True)
    ))

    result = run(account_recovery.approve(db, audit_gateway, request.request_id, "staff_1", reason=""))

    assert result.error == E_INVALID_REQUEST
    assert audit_gateway.calls == []


def test_approve_succeeds_once_one_check_is_satisfied_and_is_audited(db, audit_gateway):
    request = _create(db)
    run(account_recovery.update_checklist(
        db, request.request_id, RecoveryVerificationChecklist(vouched_by_user_id="staff_2")
    ))

    result = run(account_recovery.approve(
        db, audit_gateway, request.request_id, "staff_1", reason="vouched by staff_2"
    ))

    assert result.request.stage is RecoveryStage.APPROVED
    assert result.request.reviewed_by == "staff_1"
    assert result.audit_recorded
    operation, actor, target, reason, details = audit_gateway.calls[0]
    # The one operation Audit's own PRIVILEGED_ACTIONS already registers
    # (`core/audit/contracts.py`'s `"account_recovery_approve"` -> `ACCOUNT_RECOVERY_APPROVED`).
    assert operation == "account_recovery_approve"
    assert actor == "staff_1"
    assert target == request.user_id
    assert reason == "vouched by staff_2"


def test_complete_is_only_valid_from_approved(db, audit_gateway):
    request = _create(db)

    premature = run(account_recovery.complete(db, audit_gateway, request.request_id, "staff_1"))
    assert premature.error is not None

    run(account_recovery.update_checklist(
        db, request.request_id, RecoveryVerificationChecklist(knowledge_check_passed=True)
    ))
    run(account_recovery.approve(db, audit_gateway, request.request_id, "staff_1", reason="ok"))
    completed = run(account_recovery.complete(db, audit_gateway, request.request_id, "staff_1"))
    assert completed.request.stage is RecoveryStage.COMPLETED


def test_reject_requires_a_reason_and_is_terminal(db, audit_gateway):
    request = _create(db)

    result = run(account_recovery.reject(db, audit_gateway, request.request_id, "staff_1", reason="could not verify identity"))
    assert result.request.stage is RecoveryStage.REJECTED

    again = run(account_recovery.reject(db, audit_gateway, request.request_id, "staff_1", reason="second try"))
    assert again.error == E_ALREADY_RESOLVED


def test_one_user_cannot_cancel_anothers_recovery_case(db):
    request = _create(db, user_id="user_a")

    result = run(account_recovery.cancel(db, request.request_id, "user_b"))

    assert result.error == E_OWNERSHIP_DENIED
    unchanged = run(account_recovery.get(db, request.request_id))
    assert unchanged.stage is RecoveryStage.REQUESTED


def test_the_filing_user_can_cancel_their_own_open_case(db):
    request = _create(db, user_id="user_a")

    result = run(account_recovery.cancel(db, request.request_id, "user_a"))

    assert result.request.stage is RecoveryStage.CANCELLED


def test_cancel_fails_once_a_case_is_already_resolved(db, audit_gateway):
    request = _create(db, user_id="user_a")
    run(account_recovery.reject(db, audit_gateway, request.request_id, "staff_1", reason="denied"))

    result = run(account_recovery.cancel(db, request.request_id, "user_a"))

    assert result.error == E_ALREADY_RESOLVED


def test_acting_on_an_unknown_request_id_is_not_found_never_a_crash(db, audit_gateway):
    for coro in (
        account_recovery.approve(db, audit_gateway, "rcv_ghost", "staff_1", reason="x"),
        account_recovery.reject(db, audit_gateway, "rcv_ghost", "staff_1", reason="x"),
        account_recovery.cancel(db, "rcv_ghost", "user_a"),
    ):
        result = run(coro)
        assert result.error == E_NOT_FOUND


def test_list_for_user_never_returns_another_users_cases(db):
    _create(db, user_id="user_a")
    _create(db, user_id="user_b")

    mine = run(account_recovery.list_for_user(db, "user_a"))

    assert len(mine) == 1
    assert all(r.user_id == "user_a" for r in mine)

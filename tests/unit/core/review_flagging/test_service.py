"""`ReviewFlaggingServicer` — the real assembly point wiring `lifecycle.FlagStore` and
`audit_screen.build_audit_view` to `review_flagging.proto`'s wire surface. This was a
real, complete gap: every module the servicer calls already existed and was
independently tested, but there was no `.proto`, no `service.py`, and no generated stubs
in this package at all until this session (`service.py`'s own module docstring)."""

from __future__ import annotations

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.review_flagging.generated import review_flagging_pb2 as pb  # noqa: E402
from core.review_flagging.service import ReviewFlaggingServicer  # noqa: E402

from .conftest import run  # noqa: E402


def test_create_flag_rpc_creates_an_open_flag(store):
    servicer = ReviewFlaggingServicer(store)

    response = run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="vat_math_mismatch", user_id="user-1", receipt_id="receipt-1",
        created_by="reconciliation", payload={"expected": "100.00", "actual": "95.00"},
    )))

    assert response.error_code == ""
    assert response.flag.status == "open"
    assert response.flag.flag_type == "vat_math_mismatch"
    assert dict(response.flag.payload) == {"expected": "100.00", "actual": "95.00"}


def test_create_flag_rpc_rejects_a_missing_required_field(store):
    servicer = ReviewFlaggingServicer(store)

    response = run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="", user_id="user-1", receipt_id="receipt-1", created_by="reconciliation",
    )))

    assert response.error_code == "INVALID_FLAG_REQUEST"


def test_resolve_flag_rpc_denies_an_unresolvable_session(store):
    servicer = ReviewFlaggingServicer(store)
    created = run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="vat_math_mismatch", user_id="user-1", receipt_id="receipt-1", created_by="reconciliation",
    )))

    response = run(servicer.ResolveFlag(pb.ResolveFlagRequest(
        flag_id=created.flag.flag_id, resolution_note="x", session_id="not-a-real-session",
    )))

    assert response.error_code == "ROLE_FORBIDDEN"


def test_resolve_flag_rpc_self_assigns_and_resolves_for_a_real_staff_session(store):
    servicer = ReviewFlaggingServicer(store)
    created = run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="vat_math_mismatch", user_id="user-1", receipt_id="receipt-1", created_by="reconciliation",
    )))

    response = run(servicer.ResolveFlag(pb.ResolveFlagRequest(
        flag_id=created.flag.flag_id, resolution_note="fixed manually", session_id="sess-staff",
    )))

    assert response.error_code == ""
    assert response.flag.status == "resolved"
    assert response.flag.assigned_to == "staff-1"
    assert response.flag.resolved_by == "staff-1"


def test_resolve_flag_rpc_rejects_a_second_resolution_of_a_terminal_flag(store):
    servicer = ReviewFlaggingServicer(store)
    created = run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="vat_math_mismatch", user_id="user-1", receipt_id="receipt-1", created_by="reconciliation",
    )))
    run(servicer.ResolveFlag(pb.ResolveFlagRequest(
        flag_id=created.flag.flag_id, resolution_note="fixed", session_id="sess-staff",
    )))

    response = run(servicer.ResolveFlag(pb.ResolveFlagRequest(
        flag_id=created.flag.flag_id, resolution_note="again", session_id="sess-staff",
    )))

    assert response.error_code == "INVALID_STAGE_TRANSITION"


def test_dismiss_flag_rpc_marks_dismissed_not_resolved(store):
    servicer = ReviewFlaggingServicer(store)
    created = run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="vat_math_mismatch", user_id="user-1", receipt_id="receipt-1", created_by="reconciliation",
    )))

    response = run(servicer.DismissFlag(pb.DismissFlagRequest(
        flag_id=created.flag.flag_id, reason="false positive", session_id="sess-staff",
    )))

    assert response.error_code == ""
    assert response.flag.status == "dismissed"


def test_assign_flag_rpc_lets_an_owner_reassign_an_already_assigned_flag(store):
    servicer = ReviewFlaggingServicer(store)
    created = run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="vat_math_mismatch", user_id="user-1", receipt_id="receipt-1", created_by="reconciliation",
    )))
    run(servicer.AssignFlag(pb.AssignFlagRequest(
        flag_id=created.flag.flag_id, assignee_user_id="staff-1", session_id="sess-staff",
    )))

    response = run(servicer.AssignFlag(pb.AssignFlagRequest(
        flag_id=created.flag.flag_id, assignee_user_id="staff-2", session_id="sess-owner",
    )))

    assert response.error_code == ""
    assert response.flag.assigned_to == "staff-2"


def test_assign_flag_rpc_denies_a_staff_member_taking_over_anothers_assignment(store):
    servicer = ReviewFlaggingServicer(store)
    created = run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="vat_math_mismatch", user_id="user-1", receipt_id="receipt-1", created_by="reconciliation",
    )))
    run(servicer.AssignFlag(pb.AssignFlagRequest(
        flag_id=created.flag.flag_id, assignee_user_id="staff-1", session_id="sess-staff",
    )))

    response = run(servicer.AssignFlag(pb.AssignFlagRequest(
        flag_id=created.flag.flag_id, assignee_user_id="staff-2", session_id="sess-staff-2",
    )))

    assert response.error_code == "OWNERSHIP_DENIED"


def test_list_flags_rpc_filters_by_receipt_id(store):
    servicer = ReviewFlaggingServicer(store)
    run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="vat_math_mismatch", user_id="user-1", receipt_id="receipt-1", created_by="reconciliation",
    )))
    run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="tin_format_malformed", user_id="user-1", receipt_id="receipt-2", created_by="reconciliation",
    )))

    response = run(servicer.ListFlags(pb.ListFlagsRequest(receipt_id="receipt-1")))

    assert response.total_matching == 1
    assert response.flags[0].receipt_id == "receipt-1"


def test_get_audit_view_rpc_includes_flags_raised_for_the_receipt(store):
    servicer = ReviewFlaggingServicer(store)
    run(servicer.CreateFlag(pb.CreateFlagRequest(
        flag_type="vat_math_mismatch", user_id="user-1", receipt_id="receipt-1", created_by="reconciliation",
    )))

    response = run(servicer.GetAuditView(pb.AuditViewRequest(receipt_id="receipt-1")))

    assert response.error_code == ""
    assert len(response.flags) == 1
    assert response.flags[0].receipt_id == "receipt-1"


def test_get_audit_view_rpc_on_a_receipt_with_no_flags_returns_an_empty_but_valid_view(store):
    servicer = ReviewFlaggingServicer(store)

    response = run(servicer.GetAuditView(pb.AuditViewRequest(receipt_id="never-flagged")))

    assert response.error_code == ""
    assert list(response.flags) == []

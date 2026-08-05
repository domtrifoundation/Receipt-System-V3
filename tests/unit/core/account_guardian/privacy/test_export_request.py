"""Data portability export requests (`privacy/export_request.py`, deep-dive §6.2)."""

from __future__ import annotations

from core.account_guardian.contracts import ExportStatus
from core.account_guardian.errors import E_NOT_FOUND
from core.account_guardian.privacy import export_request

from ..conftest import run


def test_successful_export_is_ready_with_a_blob_ref_and_is_audited(db, audit_gateway, persistence_gateway):
    result = run(export_request.request_export(db, audit_gateway, persistence_gateway, "user_a"))

    assert result.request.status is ExportStatus.READY
    assert result.request.export_blob_ref is not None
    assert result.audit_recorded
    operation, actor, target, reason, details = audit_gateway.calls[0]
    assert operation == "account_guardian_export_requested"
    assert actor == target == "user_a"
    assert "RA 10173" in reason  # the legal grounding the deep-dive names, §6.1


def test_a_failing_persistence_call_degrades_to_failed_status_not_a_crash(db, audit_gateway, persistence_gateway):
    """The real, current gap (`gateways.py`): Persistence has no generated gRPC surface at
    all yet, so `UnavailablePersistenceGateway` always reports failure in production. This
    test exercises the same degrade-to-`FAILED` path with a fake standing in for "the call
    failed", proving this module never raises or silently claims success either way."""
    persistence_gateway.ok = False

    result = run(export_request.request_export(db, audit_gateway, persistence_gateway, "user_a"))

    assert result.request.status is ExportStatus.FAILED
    assert result.request.export_blob_ref is None
    assert result.request.error_detail


def test_request_status_reads_back_what_was_recorded(db, audit_gateway, persistence_gateway):
    created = run(export_request.request_export(db, audit_gateway, persistence_gateway, "user_a")).request

    status = run(export_request.request_status(db, created.request_id))

    assert status.request.request_id == created.request_id
    assert status.request.status is ExportStatus.READY


def test_status_of_an_unknown_request_is_not_found(db):
    result = run(export_request.request_status(db, "exp_ghost"))
    assert result.error == E_NOT_FOUND


def test_list_for_user_never_returns_another_users_exports(db, audit_gateway, persistence_gateway):
    run(export_request.request_export(db, audit_gateway, persistence_gateway, "user_a"))
    run(export_request.request_export(db, audit_gateway, persistence_gateway, "user_b"))

    mine = run(export_request.list_for_user(db, "user_a"))

    assert len(mine) == 1
    assert all(r.user_id == "user_a" for r in mine)

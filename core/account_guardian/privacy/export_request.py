"""Data portability — built on Persistence's Export Framework, not a separate mechanism
(deep-dive §6.2).

A data-portability export is structurally just another `ExportProvider` — Persistence's own
`data_portability` provider (`core/persistence/exports/providers/data_portability.py`)
already exists and covers "every table holding this user's own data", exactly what §6.2
asks for. This module's job stops at intake and record-keeping: register the request, call
through `gateways.PersistenceGateway`, and fold whatever comes back into a durable
`DataExportRequest` row.

**Real, current gap** (`gateways.py`): Persistence has specified `GenerateExport` in
`persistence.proto` but has not generated a gRPC servicer for it at all yet — there is no
`core/persistence/generated/` package. Every call through `UnavailablePersistenceGateway`
(the default) degrades to `ExportStatus.FAILED` with a clear detail rather than hanging or
raising. Once Persistence's own gRPC surface exists, wiring a real `PersistenceGateway` here
requires no change to this module — only to which gateway `service.py` constructs.

The deep-dive's own sketch (§6.2) notes a real export should run as a Background Worker
(idle-time class), not synchronously in the request. Background Workers has no
implementation in this build (`docs/PROCESS_TOPOLOGY.md`'s roster), so this module calls
through synchronously today and records whatever `PersistenceGateway` returns immediately —
correct behaviour for this build, and a straightforward drop-in once that scheduler exists,
since the actual generation call does not change, only who invokes it and when.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ..contracts import DataExportRequest, ExportRequestResult, ExportStatus, utcnow
from ..errors import NotFound
from ..gateways import AuditGateway, PersistenceGateway, PROPOSED_AUDIT_OPERATIONS
from ..store import AccountGuardianDatabase, in_thread

#: Persistence's own registered provider name for this scope (deep-dive §6.2) — "everything
#: we hold about you", not the curated business view `excel_general` produces.
DATA_PORTABILITY_PROVIDER = "data_portability"


def new_request_id() -> str:
    return f"exp_{uuid.uuid4().hex}"


def _row_to_request(row) -> DataExportRequest:
    from core.persistence.contracts import BlobRef

    return DataExportRequest(
        request_id=row["request_id"],
        user_id=row["user_id"],
        requested_at=datetime.fromisoformat(row["requested_at"]),
        status=ExportStatus(row["status"]),
        export_blob_ref=BlobRef(row["export_logical_id"]) if row["export_logical_id"] else None,
        error_detail=row["error_detail"] or "",
    )


def _get_sync(db: AccountGuardianDatabase, request_id: str) -> DataExportRequest | None:
    row = db.query_one("SELECT * FROM export_requests WHERE request_id = ?", (request_id,))
    return _row_to_request(row) if row else None


async def get(db: AccountGuardianDatabase, request_id: str) -> DataExportRequest | None:
    return await in_thread(_get_sync, db, request_id)


async def list_for_user(db: AccountGuardianDatabase, user_id: str) -> tuple[DataExportRequest, ...]:
    def _read() -> list[DataExportRequest]:
        rows = db.query_all(
            "SELECT * FROM export_requests WHERE user_id = ? ORDER BY requested_at DESC",
            (user_id,),
        )
        return [_row_to_request(r) for r in rows]

    return tuple(await in_thread(_read))


async def request_export(
    db: AccountGuardianDatabase,
    audit: AuditGateway,
    persistence: PersistenceGateway,
    user_id: str,
    provider_name: str = DATA_PORTABILITY_PROVIDER,
) -> ExportRequestResult:
    request_id = new_request_id()
    now = utcnow()

    def _insert(status: ExportStatus) -> None:
        db.write(
            "INSERT INTO export_requests (request_id, user_id, requested_at, status,"
            " export_logical_id, error_detail) VALUES (?,?,?,?,NULL,'')",
            (request_id, user_id, now.isoformat(), status.value),
        )

    await in_thread(_insert, ExportStatus.PROCESSING)

    outcome = await persistence.generate_export(user_id, provider_name)

    def _resolve() -> DataExportRequest:
        if outcome.ok and outcome.export_blob_ref is not None:
            status = ExportStatus.READY
            logical_id = outcome.export_blob_ref.logical_id
            error_detail = ""
        else:
            status = ExportStatus.FAILED
            logical_id = None
            error_detail = outcome.error_detail or "export generation failed"
        db.write(
            "UPDATE export_requests SET status = ?, export_logical_id = ?, error_detail = ?"
            " WHERE request_id = ?",
            (status.value, logical_id, error_detail, request_id),
        )
        return DataExportRequest(
            request_id=request_id, user_id=user_id, requested_at=now, status=status,
            export_blob_ref=outcome.export_blob_ref, error_detail=error_detail,
        )

    request = await in_thread(_resolve)
    audit_outcome = await audit.record(
        PROPOSED_AUDIT_OPERATIONS["export_requested"], user_id, target_user_id=user_id,
        reason="user-initiated data portability export (RA 10173)",
        details={"request_id": request_id, "provider": provider_name, "ok": outcome.ok},
    )
    return ExportRequestResult(
        request=request, audit_recorded=audit_outcome.recorded,
        audit_error=audit_outcome.error_detail if not audit_outcome.recorded else "",
    )


async def request_status(db: AccountGuardianDatabase, request_id: str) -> ExportRequestResult:
    request = await get(db, request_id)
    if request is None:
        return ExportRequestResult(error=NotFound.code, error_detail=f"no such request {request_id!r}")
    return ExportRequestResult(request=request)


__all__ = [
    "DATA_PORTABILITY_PROVIDER", "get", "list_for_user", "new_request_id", "request_export",
    "request_status",
]

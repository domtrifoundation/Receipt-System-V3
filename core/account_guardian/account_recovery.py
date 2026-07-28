"""Account recovery — request intake and the staff-facing case queue (deep-dive §5).

**Not a self-service flow, and nothing in this module makes it one.** Since no local
password exists anywhere in this system (`core/auth/` §4), "recovery" always means a user
lost the authentication method(s) they had configured — a compromised SSO account, a lost
passkey, a changed phone number — and verifying who someone is without a still-working
method is inherently a manual, staff-mediated judgment call, not something safe to automate
(deep-dive §5). This module's job is the *request intake and case queue*; the actual
decision to relink an identity, register a replacement passkey, or update a phone/email an
OTP method depends on is a privileged action a human makes and this module records.

**The one automatable floor, and only one** (deep-dive §12's own open-question resolution):
`approve()` refuses to move a case to `APPROVED` unless
`RecoveryVerificationChecklist.any_check_satisfied` is true — at least one of the three
checks (knowledge, recovery contact, staff/owner vouching) must be affirmatively satisfied.
*Which* combination is actually sufficient for a given case stays a human judgment call,
deliberately not encoded as an algorithm here — this is a floor against an empty rubber
stamp, not a substitute for staff judgment.

Every stage transition below is exactly what `errors.InvalidStageTransition` and
`errors.AlreadyResolved` exist for: a request that has already reached a terminal stage, or
an attempt to skip past the one required checklist floor, is refused as data
(`docs/PRINCIPLES.md` §4.1), never silently allowed and never raised.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime

from .contracts import (
    AuthMethod,
    RecoveryRequest,
    RecoveryResult,
    RecoveryStage,
    RecoveryVerificationChecklist,
    utcnow,
)
from .errors import (
    AlreadyResolved,
    InvalidRequest,
    InvalidStageTransition,
    NotFound,
    OwnershipDenied,
    VerificationInsufficient,
)
from .gateways import AuditGateway, PROPOSED_AUDIT_OPERATIONS
from .store import AccountGuardianDatabase, in_thread

#: Stages from which staff may still act, or the requester may still cancel.
_OPEN_STAGES = (RecoveryStage.REQUESTED, RecoveryStage.UNDER_REVIEW)


def new_request_id() -> str:
    return f"rcv_{uuid.uuid4().hex}"


def _checklist_to_json(checklist: RecoveryVerificationChecklist) -> str:
    return json.dumps(asdict(checklist))


def _checklist_from_json(raw: str) -> RecoveryVerificationChecklist:
    data = json.loads(raw) if raw else {}
    return RecoveryVerificationChecklist(**data)


def _row_to_request(row) -> RecoveryRequest:
    return RecoveryRequest(
        request_id=row["request_id"],
        user_id=row["user_id"],
        requested_at=datetime.fromisoformat(row["requested_at"]),
        stage=RecoveryStage(row["stage"]),
        lost_method=AuthMethod(row["lost_method"]) if row["lost_method"] else None,
        checklist=_checklist_from_json(row["checklist_json"]),
        reviewed_by=row["reviewed_by"],
        resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
        notes=row["notes"] or "",
    )


def _get_sync(db: AccountGuardianDatabase, request_id: str) -> RecoveryRequest | None:
    row = db.query_one("SELECT * FROM recovery_requests WHERE request_id = ?", (request_id,))
    return _row_to_request(row) if row else None


async def get(db: AccountGuardianDatabase, request_id: str) -> RecoveryRequest | None:
    return await in_thread(_get_sync, db, request_id)


async def list_for_user(db: AccountGuardianDatabase, user_id: str) -> tuple[RecoveryRequest, ...]:
    """Every recovery case this user has ever filed, resolved or not — the same "entitled to
    the whole history" reasoning `core/auth/break_glass/grant.py.list_for_client_sync` uses."""

    def _read(conn=None) -> list[RecoveryRequest]:
        rows = db.query_all(
            "SELECT * FROM recovery_requests WHERE user_id = ? ORDER BY requested_at DESC",
            (user_id,),
        )
        return [_row_to_request(r) for r in rows]

    return tuple(await in_thread(_read))


async def create_request(
    db: AccountGuardianDatabase, user_id: str, lost_method: AuthMethod | None = None
) -> RecoveryResult:
    now = utcnow()
    request = RecoveryRequest(
        request_id=new_request_id(),
        user_id=user_id,
        requested_at=now,
        stage=RecoveryStage.REQUESTED,
        lost_method=lost_method,
    )

    def _write() -> None:
        db.write(
            "INSERT INTO recovery_requests (request_id, user_id, lost_method, requested_at,"
            " stage, checklist_json, reviewed_by, resolved_at, notes)"
            " VALUES (?,?,?,?,?,?,NULL,NULL,'')",
            (
                request.request_id, user_id, lost_method.value if lost_method else None,
                now.isoformat(), request.stage.value, _checklist_to_json(request.checklist),
            ),
        )

    await in_thread(_write)
    return RecoveryResult(request=request)


async def update_checklist(
    db: AccountGuardianDatabase, request_id: str, checklist: RecoveryVerificationChecklist
) -> RecoveryResult:
    """Staff records what it could verify for this case. Moves `REQUESTED` -> `UNDER_REVIEW`
    on first contact; a no-op stage-wise if a reviewer updates the checklist more than once."""
    existing = await get(db, request_id)
    if existing is None:
        return RecoveryResult(error=NotFound.code, error_detail=f"no such request {request_id!r}")
    if existing.stage not in _OPEN_STAGES:
        return RecoveryResult(
            error=AlreadyResolved.code,
            error_detail=f"request {request_id!r} is already {existing.stage.value}",
        )
    next_stage = RecoveryStage.UNDER_REVIEW

    def _write() -> None:
        db.write(
            "UPDATE recovery_requests SET checklist_json = ?, stage = ? WHERE request_id = ?",
            (_checklist_to_json(checklist), next_stage.value, request_id),
        )

    await in_thread(_write)
    updated = RecoveryRequest(
        request_id=existing.request_id, user_id=existing.user_id,
        requested_at=existing.requested_at, stage=next_stage, lost_method=existing.lost_method,
        checklist=checklist, reviewed_by=existing.reviewed_by, resolved_at=existing.resolved_at,
        notes=existing.notes,
    )
    return RecoveryResult(request=updated)


async def _resolve(
    db: AccountGuardianDatabase, audit: AuditGateway, request_id: str, reviewer_user_id: str,
    reason: str, new_stage: RecoveryStage, audit_operation: str,
) -> RecoveryResult:
    existing = await get(db, request_id)
    if existing is None:
        return RecoveryResult(error=NotFound.code, error_detail=f"no such request {request_id!r}")
    if existing.stage not in _OPEN_STAGES:
        return RecoveryResult(
            error=AlreadyResolved.code,
            error_detail=f"request {request_id!r} is already {existing.stage.value}",
        )
    if not reason or not reason.strip():
        return RecoveryResult(
            error=InvalidRequest.code,
            error_detail="a staff decision on a recovery case requires a stated reason",
        )
    if new_stage is RecoveryStage.APPROVED and not existing.checklist.any_check_satisfied:
        return RecoveryResult(
            error=VerificationInsufficient.code,
            error_detail=(
                "no verification check has been satisfied on this checklist yet — "
                "record at least one before approving"
            ),
        )

    now = utcnow()

    def _write() -> None:
        db.write(
            "UPDATE recovery_requests SET stage = ?, reviewed_by = ?, resolved_at = ?, notes = ?"
            " WHERE request_id = ?",
            (new_stage.value, reviewer_user_id, now.isoformat(), reason.strip(), request_id),
        )

    await in_thread(_write)
    resolved = RecoveryRequest(
        request_id=existing.request_id, user_id=existing.user_id,
        requested_at=existing.requested_at, stage=new_stage, lost_method=existing.lost_method,
        checklist=existing.checklist, reviewed_by=reviewer_user_id, resolved_at=now,
        notes=reason.strip(),
    )
    outcome = await audit.record(
        audit_operation, reviewer_user_id, target_user_id=existing.user_id, reason=reason,
        details={"request_id": request_id, "lost_method": (
            existing.lost_method.value if existing.lost_method else None
        )},
    )
    return RecoveryResult(
        request=resolved, audit_recorded=outcome.recorded,
        audit_error=outcome.error_detail if not outcome.recorded else "",
    )


async def approve(
    db: AccountGuardianDatabase, audit: AuditGateway, request_id: str, reviewer_user_id: str,
    reason: str,
) -> RecoveryResult:
    """The one privileged decision this module records under an operation Audit's own
    `PRIVILEGED_ACTIONS` already recognises (`"account_recovery_approve"` ->
    `ActionType.ACCOUNT_RECOVERY_APPROVED`) — comparable in stakes to a break-glass grant,
    per the deep-dive's own framing (§5), so it is logged the same way."""
    return await _resolve(
        db, audit, request_id, reviewer_user_id, reason, RecoveryStage.APPROVED,
        PROPOSED_AUDIT_OPERATIONS["recovery_approved"],
    )


async def reject(
    db: AccountGuardianDatabase, audit: AuditGateway, request_id: str, reviewer_user_id: str,
    reason: str,
) -> RecoveryResult:
    return await _resolve(
        db, audit, request_id, reviewer_user_id, reason, RecoveryStage.REJECTED,
        PROPOSED_AUDIT_OPERATIONS["recovery_rejected"],
    )


async def complete(
    db: AccountGuardianDatabase, audit: AuditGateway, request_id: str, reviewer_user_id: str,
    notes: str = "",
) -> RecoveryResult:
    """Marks the case done once whatever mechanism the approval named (a fresh SSO relink, a
    replacement passkey registration, an updated OTP phone/email) actually happened. Valid
    only from `APPROVED` — a case cannot be completed before it was ever approved."""
    existing = await get(db, request_id)
    if existing is None:
        return RecoveryResult(error=NotFound.code, error_detail=f"no such request {request_id!r}")
    if existing.stage is not RecoveryStage.APPROVED:
        return RecoveryResult(
            error=InvalidStageTransition.code,
            error_detail=f"only an APPROVED request can be completed, this one is {existing.stage.value}",
        )

    now = utcnow()

    def _write() -> None:
        db.write(
            "UPDATE recovery_requests SET stage = ?, resolved_at = ?, notes = ? WHERE request_id = ?",
            (RecoveryStage.COMPLETED.value, now.isoformat(), notes or existing.notes, request_id),
        )

    await in_thread(_write)
    resolved = RecoveryRequest(
        request_id=existing.request_id, user_id=existing.user_id,
        requested_at=existing.requested_at, stage=RecoveryStage.COMPLETED,
        lost_method=existing.lost_method, checklist=existing.checklist,
        reviewed_by=existing.reviewed_by, resolved_at=now, notes=notes or existing.notes,
    )
    outcome = await audit.record(
        PROPOSED_AUDIT_OPERATIONS["recovery_completed"], reviewer_user_id,
        target_user_id=existing.user_id, reason="account recovery completed",
        details={"request_id": request_id},
    )
    return RecoveryResult(
        request=resolved, audit_recorded=outcome.recorded,
        audit_error=outcome.error_detail if not outcome.recorded else "",
    )


async def cancel(db: AccountGuardianDatabase, request_id: str, acting_user_id: str) -> RecoveryResult:
    """Only the user who filed a case may cancel it, and only while it is still open — the
    same ownership discipline `devices.py` applies to a session id."""
    existing = await get(db, request_id)
    if existing is None:
        return RecoveryResult(error=NotFound.code, error_detail=f"no such request {request_id!r}")
    if existing.user_id != acting_user_id:
        return RecoveryResult(
            error=OwnershipDenied.code,
            error_detail=f"request {request_id!r} does not belong to this account",
        )
    if existing.stage not in _OPEN_STAGES:
        return RecoveryResult(
            error=AlreadyResolved.code,
            error_detail=f"request {request_id!r} is already {existing.stage.value}",
        )

    now = utcnow()

    def _write() -> None:
        db.write(
            "UPDATE recovery_requests SET stage = ?, resolved_at = ? WHERE request_id = ?",
            (RecoveryStage.CANCELLED.value, now.isoformat(), request_id),
        )

    await in_thread(_write)
    resolved = RecoveryRequest(
        request_id=existing.request_id, user_id=existing.user_id,
        requested_at=existing.requested_at, stage=RecoveryStage.CANCELLED,
        lost_method=existing.lost_method, checklist=existing.checklist,
        reviewed_by=existing.reviewed_by, resolved_at=now, notes=existing.notes,
    )
    return RecoveryResult(request=resolved)


__all__ = [
    "approve", "cancel", "complete", "create_request", "get", "list_for_user",
    "new_request_id", "reject", "update_checklist",
]

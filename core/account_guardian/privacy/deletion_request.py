"""Right to erasure — the grace-period lifecycle (deep-dive §6.3).

Every stage in `contracts.DeletionStage` is real here: `REQUESTED` -> (billing clean?) ->
`GRACE_PERIOD` or `BILLING_HOLD` -> (grace elapses, billing clean) -> `PROCESSING` ->
`COMPLETE`, cancellable at any point before `PROCESSING` starts and never after (deep-dive:
"once `PROCESSING` has begun, it's genuinely irreversible and this call correctly fails
rather than pretending to succeed").

**The grace period *is* how the Billing interaction resolves** (deep-dive §6.3): a request
immediately asks `gateways.BillingGateway` whether the account's subscription state is
clean. Clear -> `GRACE_PERIOD` starts counting down immediately. Not clear -> `BILLING_HOLD`,
never silently skipped and never silently proceeded past (`docs/PRINCIPLES.md` §4.3).
`advance()` is what a Background Workers sweep re-runs the same check through — this module
exposes it as a plain function precisely so a scheduler can call it, not because this
package schedules anything itself (Background Workers has no implementation in this build;
wiring the actual periodic call is that API's own job once it exists).

**At most one active (non-terminal) deletion lifecycle per user**, enforced structurally by
`store.py`'s own partial unique index — `request_deletion()` checks for one first so it can
report `errors.AlreadyResolved` with a useful message rather than surfacing a raw
`sqlite3.IntegrityError`.

Actual erasure, once `PROCESSING` starts, goes through `gateways.PersistenceGateway
.erase_account()` — real Persistence's own normal write path once that gateway is wired to a
live Persistence gRPC surface (`gateways.py`'s own documented gap: no such surface exists in
this build yet), never a special-cased bypass of Persistence's own Historian trail.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from ..contracts import DeletionRequest, DeletionResult, DeletionStage, utcnow
from ..errors import AlreadyResolved, InvalidStageTransition, NotFound, OwnershipDenied
from ..gateways import AuditGateway, BillingGateway, PersistenceGateway, PROPOSED_AUDIT_OPERATIONS
from ..store import AccountGuardianDatabase, in_thread

DEFAULT_GRACE_PERIOD_DAYS = 30

#: Stages `contracts.DeletionRequest.cancellable` already names — kept as the single source
#: of truth there; re-derived here would be a second place for the two to drift.
_TERMINAL_STAGES = (DeletionStage.COMPLETE, DeletionStage.CANCELLED)


def new_request_id() -> str:
    return f"del_{uuid.uuid4().hex}"


def _row_to_request(row) -> DeletionRequest:
    return DeletionRequest(
        request_id=row["request_id"],
        user_id=row["user_id"],
        requested_at=datetime.fromisoformat(row["requested_at"]),
        stage=DeletionStage(row["stage"]),
        grace_period_ends_at=(
            datetime.fromisoformat(row["grace_period_ends_at"])
            if row["grace_period_ends_at"] else None
        ),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
    )


def _get_sync(db: AccountGuardianDatabase, request_id: str) -> DeletionRequest | None:
    row = db.query_one("SELECT * FROM deletion_requests WHERE request_id = ?", (request_id,))
    return _row_to_request(row) if row else None


def _active_for_user_sync(db: AccountGuardianDatabase, user_id: str) -> DeletionRequest | None:
    row = db.query_one(
        "SELECT * FROM deletion_requests WHERE user_id = ? AND stage NOT IN ('complete',"
        " 'cancelled') LIMIT 1",
        (user_id,),
    )
    return _row_to_request(row) if row else None


async def get(db: AccountGuardianDatabase, request_id: str) -> DeletionRequest | None:
    return await in_thread(_get_sync, db, request_id)


async def get_active_for_user(db: AccountGuardianDatabase, user_id: str) -> DeletionRequest | None:
    return await in_thread(_active_for_user_sync, db, user_id)


async def list_for_user(db: AccountGuardianDatabase, user_id: str) -> tuple[DeletionRequest, ...]:
    def _read() -> list[DeletionRequest]:
        rows = db.query_all(
            "SELECT * FROM deletion_requests WHERE user_id = ? ORDER BY requested_at DESC",
            (user_id,),
        )
        return [_row_to_request(r) for r in rows]

    return tuple(await in_thread(_read))


async def request_deletion(
    db: AccountGuardianDatabase,
    audit: AuditGateway,
    billing: BillingGateway,
    user_id: str,
    grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
) -> DeletionResult:
    existing = await get_active_for_user(db, user_id)
    if existing is not None:
        return DeletionResult(
            error=AlreadyResolved.code,
            error_detail=(
                f"an active deletion request {existing.request_id!r} already exists for "
                f"this account, in stage {existing.stage.value!r}"
            ),
        )

    clearance = await billing.resolve_deletion_clearance(user_id)
    now = utcnow()
    request_id = new_request_id()
    if clearance.clear:
        stage = DeletionStage.GRACE_PERIOD
        grace_ends = now + timedelta(days=grace_period_days)
    else:
        stage = DeletionStage.BILLING_HOLD
        grace_ends = None

    def _write() -> None:
        db.write(
            "INSERT INTO deletion_requests (request_id, user_id, requested_at, stage,"
            " grace_period_ends_at, completed_at) VALUES (?,?,?,?,?,NULL)",
            (
                request_id, user_id, now.isoformat(), stage.value,
                grace_ends.isoformat() if grace_ends else None,
            ),
        )

    await in_thread(_write)
    request = DeletionRequest(
        request_id=request_id, user_id=user_id, requested_at=now, stage=stage,
        grace_period_ends_at=grace_ends,
    )
    outcome = await audit.record(
        PROPOSED_AUDIT_OPERATIONS["deletion_requested"], user_id, target_user_id=user_id,
        reason="user-initiated account deletion (right to erasure, RA 10173)",
        details={"request_id": request_id, "stage": stage.value, "billing_detail": clearance.detail},
    )
    return DeletionResult(
        request=request, audit_recorded=outcome.recorded,
        audit_error=outcome.error_detail if not outcome.recorded else "",
    )


async def cancel_deletion(
    db: AccountGuardianDatabase, audit: AuditGateway, request_id: str, acting_user_id: str
) -> DeletionResult:
    existing = await get(db, request_id)
    if existing is None:
        return DeletionResult(error=NotFound.code, error_detail=f"no such request {request_id!r}")
    if existing.user_id != acting_user_id:
        return DeletionResult(
            error=OwnershipDenied.code,
            error_detail=f"request {request_id!r} does not belong to this account",
        )
    if not existing.cancellable:
        return DeletionResult(
            error=InvalidStageTransition.code,
            error_detail=(
                f"request {request_id!r} is in stage {existing.stage.value!r}, which is no "
                f"longer cancellable — deletion is irreversible once PROCESSING starts"
            ),
        )

    def _write() -> None:
        db.write(
            "UPDATE deletion_requests SET stage = ? WHERE request_id = ?",
            (DeletionStage.CANCELLED.value, request_id),
        )

    await in_thread(_write)
    resolved = DeletionRequest(
        request_id=existing.request_id, user_id=existing.user_id,
        requested_at=existing.requested_at, stage=DeletionStage.CANCELLED,
        grace_period_ends_at=existing.grace_period_ends_at,
    )
    outcome = await audit.record(
        PROPOSED_AUDIT_OPERATIONS["deletion_cancelled"], acting_user_id,
        target_user_id=acting_user_id, reason="user cancelled their own deletion request",
        details={"request_id": request_id},
    )
    return DeletionResult(
        request=resolved, audit_recorded=outcome.recorded,
        audit_error=outcome.error_detail if not outcome.recorded else "",
    )


async def advance(
    db: AccountGuardianDatabase,
    audit: AuditGateway,
    persistence: PersistenceGateway,
    billing: BillingGateway,
    request_id: str,
    now: datetime | None = None,
) -> DeletionResult:
    """One request's worth of what a Background Workers sweep repeatedly calls (deep-dive
    §6.3's own flagged gap: something has to check on a `GRACE_PERIOD` row or it sits there
    forever). Idempotent re-entry is deliberate: calling this against a request that is not
    yet due, or already resolved, is a no-op that returns the request unchanged rather than
    an error — a sweep runs on a timer, not on a guarantee that every row it visits is ready.
    """
    existing = await get(db, request_id)
    if existing is None:
        return DeletionResult(error=NotFound.code, error_detail=f"no such request {request_id!r}")
    moment = now or utcnow()

    if existing.stage is DeletionStage.BILLING_HOLD:
        clearance = await billing.resolve_deletion_clearance(existing.user_id)
        if not clearance.clear:
            return DeletionResult(request=existing)  # still held, nothing changed
        grace_ends = moment + timedelta(days=DEFAULT_GRACE_PERIOD_DAYS)

        def _to_grace() -> None:
            db.write(
                "UPDATE deletion_requests SET stage = ?, grace_period_ends_at = ?"
                " WHERE request_id = ?",
                (DeletionStage.GRACE_PERIOD.value, grace_ends.isoformat(), request_id),
            )

        await in_thread(_to_grace)
        return DeletionResult(request=DeletionRequest(
            request_id=existing.request_id, user_id=existing.user_id,
            requested_at=existing.requested_at, stage=DeletionStage.GRACE_PERIOD,
            grace_period_ends_at=grace_ends,
        ))

    if existing.stage is DeletionStage.GRACE_PERIOD:
        if existing.grace_period_ends_at is None or existing.grace_period_ends_at > moment:
            return DeletionResult(request=existing)  # not due yet
        clearance = await billing.resolve_deletion_clearance(existing.user_id)
        if not clearance.clear:
            def _to_hold() -> None:
                db.write(
                    "UPDATE deletion_requests SET stage = ? WHERE request_id = ?",
                    (DeletionStage.BILLING_HOLD.value, request_id),
                )

            await in_thread(_to_hold)
            return DeletionResult(request=DeletionRequest(
                request_id=existing.request_id, user_id=existing.user_id,
                requested_at=existing.requested_at, stage=DeletionStage.BILLING_HOLD,
            ))

        def _to_processing() -> None:
            db.write(
                "UPDATE deletion_requests SET stage = ? WHERE request_id = ?",
                (DeletionStage.PROCESSING.value, request_id),
            )

        await in_thread(_to_processing)
        processing = DeletionRequest(
            request_id=existing.request_id, user_id=existing.user_id,
            requested_at=existing.requested_at, stage=DeletionStage.PROCESSING,
        )
        return await _process(db, audit, persistence, processing)

    if existing.stage is DeletionStage.PROCESSING:
        return await _process(db, audit, persistence, existing)

    return DeletionResult(request=existing)  # REQUESTED, COMPLETE, or CANCELLED: nothing to do


async def _process(
    db: AccountGuardianDatabase, audit: AuditGateway, persistence: PersistenceGateway,
    request: DeletionRequest,
) -> DeletionResult:
    """Erasure itself, once `PROCESSING` has started — genuinely irreversible past this
    point (deep-dive §6.3), so this never re-checks billing or cancellability again."""
    outcome = await persistence.erase_account(request.user_id)
    if not outcome.ok:
        # Stays in PROCESSING. A failed erasure attempt is not silently downgraded back to a
        # cancellable stage — the next sweep pass retries the same, still-irreversible step.
        return DeletionResult(
            request=request, error=outcome.error, error_detail=outcome.error_detail,
        )

    completed_at = outcome.erased_at or utcnow()

    def _write() -> None:
        db.write(
            "UPDATE deletion_requests SET stage = ?, completed_at = ? WHERE request_id = ?",
            (DeletionStage.COMPLETE.value, completed_at.isoformat(), request.request_id),
        )

    await in_thread(_write)
    resolved = DeletionRequest(
        request_id=request.request_id, user_id=request.user_id,
        requested_at=request.requested_at, stage=DeletionStage.COMPLETE,
        completed_at=completed_at,
    )
    audit_outcome = await audit.record(
        PROPOSED_AUDIT_OPERATIONS["deletion_completed"], "system", target_user_id=request.user_id,
        reason="account erasure completed after grace period and billing clearance",
        details={"request_id": request.request_id},
    )
    return DeletionResult(
        request=resolved, audit_recorded=audit_outcome.recorded,
        audit_error=audit_outcome.error_detail if not audit_outcome.recorded else "",
    )


__all__ = [
    "DEFAULT_GRACE_PERIOD_DAYS", "advance", "cancel_deletion", "get", "get_active_for_user",
    "list_for_user", "new_request_id", "request_deletion",
]

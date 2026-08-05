"""The flag lifecycle: create, assign, resolve, dismiss (`v3-deepdive-25-review-flagging-
api.md` §4). This is a real state machine, not a status column anyone can overwrite — every
transition is checked against `contracts.VALID_TRANSITIONS` before a single row is updated,
and an invalid transition is rejected explicitly, the same discipline
`core/account_guardian/privacy/deletion_request.py` follows for its own lifecycle.

**Role resolution fails closed** (`docs/PRINCIPLES.md` §4.2). Assigning, resolving or
dismissing a flag requires a real `staff`/`owner` role resolved server-side from the
caller's own session (`gateways.SessionRoleResolver`, wired to Auth's real `ValidateSession`
by default) — never a role the caller asserts about itself. A session this package cannot
vouch for is denied, identically to an insufficient role; only the audit trail below tells
the two apart.

**Ownership is a second, narrower gate on top of the role gate** (§8's own resolved routing
policy): "a shared open queue, self-assign — any staff member can self-assign, an owner can
reassign." Concretely, `_can_act` grants a `staff`-role caller action on a flag only while it
is unassigned (auto-self-assigning it as part of the same call, §4's own "OPEN reaches
RESOLVED/DISMISSED directly" transition) or already assigned to *that* caller; a `staff`
member can never resolve, dismiss, or take over a flag another staff member is already
working. `owner` bypasses the ownership gate entirely, exactly as it bypasses the assignment
gate in `assign_flag`.

**Every resolution attempt produces an Audit entry, success or refusal alike** — this is the
task's own explicit requirement, and it is what makes a role/ownership denial itself an
inspectable fact rather than a silent no-op an attacker (or a confused staff member) leaves
no trace of. `gateways.PROPOSED_AUDIT_OPERATIONS` documents the real gap: these operation
names are not registered in Audit's own closed vocabulary yet, so a real call today comes
back `recorded=False, error_code="UNKNOWN_ACTION"` — reported on the result via the
`audit_records_degraded` counter, never swallowed (`docs/PRINCIPLES.md` §4.3).

**Resolution's own data-change edit, when one is supplied, is applied before the flag is
ever marked `RESOLVED`** (§4: "routes through the same edit-entry-point mechanism... never a
special-cased bypass"). A write that fails leaves the flag exactly where it was.

**Concurrency**: async I/O throughout, no compute-bound work of its own (§5) — every blocking
SQLite call is handed to a worker thread via `asyncio.to_thread`, the same pattern
`core/audit/writer.py` and `core/audit/query.py` use for the identical reason.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from pathlib import Path

from .contracts import (
    RESOLVER_ROLES,
    AssignFlagRequest,
    AuditRecorder,
    CreateFlagRequest,
    DismissFlagRequest,
    Flag,
    FlagNotifier,
    FlagResult,
    FlagStatus,
    FlagTypeValidator,
    ListFlagsQuery,
    ListFlagsResult,
    PersistenceWriteGateway,
    ResolveFlagRequest,
    SessionRoleResolver,
    VALID_TRANSITIONS,
    utcnow,
)
from .db import connect, flag_to_insert_row, row_to_flag
from .errors import (
    EditWriteFailed,
    InvalidFlagRequest,
    InvalidStageTransition,
    OwnershipDenied,
    RoleForbidden,
    UnknownFlag,
    code_for,
)
from .gateways import (
    DenyAllSessions,
    GrpcAuditRecorder,
    GrpcSessionRoleResolver,
    NullFlagNotifier,
    PROPOSED_AUDIT_OPERATIONS,
    PermissiveFlagTypeValidator,
    UnavailablePersistenceWriteGateway,
)
from .metrics import FlagMetricsCollector

import uuid


def new_flag_id() -> str:
    """A UUID4, not a sequence number — mirrors `core/audit/writer.py::new_event_id`'s own
    reasoning: a caller needs a stable id before the row is committed, and a guessable id
    would make a flag's existence trivially probeable."""
    return f"flg_{uuid.uuid4().hex}"


def can_transition(current: FlagStatus, target: FlagStatus) -> bool:
    """Whether `contracts.VALID_TRANSITIONS` permits moving from `current` to `target`.

    A pure function over the one table this whole state machine is built from — kept out of
    `contracts.py` because `contracts.py` holds no logic (`docs/PRINCIPLES.md` §1.1), and
    tested directly so "every invalid transition is rejected" is checkable without a store.
    """
    return target in VALID_TRANSITIONS.get(current, frozenset())


def _can_act(flag: Flag, actor_user_id: str, role: str) -> bool:
    """Whether this resolved `(actor_user_id, role)` may resolve, dismiss, or otherwise act
    on `flag` right now (§8's own resolved routing policy, restated in this module's own
    docstring). Assumes the role gate (`role in RESOLVER_ROLES`) has already passed."""
    if role == "owner":
        return True
    return flag.assigned_to is None or flag.assigned_to == actor_user_id


def _assign_permitted(flag: Flag, actor_user_id: str, role: str, assignee_user_id: str) -> bool:
    """Whether this resolved caller may set `flag.assigned_to = assignee_user_id` (§8).

    `owner` may assign or reassign to anyone. A `staff`-role caller may only self-assign an
    unassigned flag — assigning it to a third party, or touching an already-assigned flag at
    all, is an owner-only reassignment.
    """
    if role == "owner":
        return True
    return flag.assigned_to is None and assignee_user_id == actor_user_id


class FlagStore:
    """The whole lifecycle surface: create, assign, resolve, dismiss, list, get.

    Construct with no arguments for the real top-level database and the real Auth/Audit/
    Notifications adapters, or pass explicit seams in tests. Every external dependency has a
    small Protocol seam (`contracts.py`) and a concrete default (`gateways.py`) — nothing in
    this module imports another Core API's own logic module directly (`docs/PRINCIPLES.md`
    §1.3).
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        flag_type_validator: FlagTypeValidator | None = None,
        role_resolver: SessionRoleResolver | None = None,
        audit: AuditRecorder | None = None,
        notifier: FlagNotifier | None = None,
        edit_gateway: PersistenceWriteGateway | None = None,
        metrics: FlagMetricsCollector | None = None,
    ) -> None:
        self._conn = connect(db_path)
        self._lock = asyncio.Lock()
        self._validator = flag_type_validator or PermissiveFlagTypeValidator()
        self._role_resolver = role_resolver or GrpcSessionRoleResolver()
        self._audit = audit or GrpcAuditRecorder()
        self._notifier = notifier or NullFlagNotifier()
        self._edit_gateway = edit_gateway or UnavailablePersistenceWriteGateway()
        self._metrics = metrics or FlagMetricsCollector()

    @property
    def metrics(self) -> FlagMetricsCollector:
        return self._metrics

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------------- create

    async def create_flag(self, request: CreateFlagRequest) -> FlagResult:
        """System-to-system, never session-gated (Reconciliation, Content Security, Reimport
        — §1's own list of callers). `flag_type` is checked against `self._validator` for
        metrics purposes only; an unrecognised code is still accepted (§4.4) — a real signal
        a producer API raised in good faith is never lost over a labeling gap."""
        if not request.flag_type or not request.user_id or not request.receipt_id or not request.created_by:
            exc = InvalidFlagRequest(
                "flag_type, user_id, receipt_id and created_by are all required"
            )
            self._metrics.increment("flags_create_rejected")
            return FlagResult(error_code=code_for(exc), error_detail=str(exc))

        if not self._validator.is_known(request.flag_type):
            self._metrics.increment("flag_type_unrecognized")

        flag = Flag(
            flag_id=new_flag_id(),
            flag_type=request.flag_type,
            user_id=request.user_id,
            receipt_id=request.receipt_id,
            status=FlagStatus.OPEN,
            created_by=request.created_by,
            created_at=utcnow(),
            payload=request.payload,
        )
        try:
            await asyncio.to_thread(self._insert, flag)
        except sqlite3.DatabaseError as exc:
            self._metrics.increment("flags_create_rejected")
            return FlagResult(error_code="STORE_UNAVAILABLE", error_detail=str(exc))

        self._metrics.increment("flags_created")
        await self._maybe_notify(flag)
        return FlagResult(flag=flag)

    async def _maybe_notify(self, flag: Flag) -> None:
        """§8's resolved severity split: an immediate alert for high-stakes flag types only.
        A failed or skipped notification never fails flag creation itself (§4.4) — the flag
        is already durably created by the time this runs."""
        if not flag.is_high_stakes:
            self._metrics.increment("notifications_skipped_routine")
            return
        try:
            sent = await self._notifier.notify_new_flag(flag)
        except Exception:  # noqa: BLE001 - a broken notifier must not fail flag creation
            sent = False
        self._metrics.increment("notifications_sent" if sent else "notifications_failed")

    # -------------------------------------------------------------------------- assign

    async def assign_flag(self, request: AssignFlagRequest, session_id: str) -> FlagResult:
        resolved = await self._role_resolver.resolve(session_id)
        if resolved is None or resolved[1] not in RESOLVER_ROLES:
            self._metrics.increment("resolutions_denied_role")
            exc = RoleForbidden()
            return FlagResult(error_code=code_for(exc), error_detail=str(exc))
        actor_user_id, role = resolved

        flag = await self._get(request.flag_id)
        if flag is None:
            exc = UnknownFlag(request.flag_id)
            return FlagResult(error_code=code_for(exc), error_detail=str(exc))

        if flag.is_terminal:
            self._metrics.increment("invalid_transitions_rejected")
            exc = InvalidStageTransition(
                f"{flag.flag_id!r} is already {flag.status.value!r} and cannot be reassigned"
            )
            return FlagResult(error_code=code_for(exc), error_detail=str(exc))

        if not _assign_permitted(flag, actor_user_id, role, request.assignee_user_id):
            self._metrics.increment("resolutions_denied_ownership")
            exc = OwnershipDenied(
                f"{actor_user_id!r} (role {role!r}) may not assign {flag.flag_id!r} to "
                f"{request.assignee_user_id!r}"
            )
            return FlagResult(error_code=code_for(exc), error_detail=str(exc))

        was_assigned = flag.assigned_to is not None
        updated = replace(flag, status=FlagStatus.ASSIGNED, assigned_to=request.assignee_user_id)
        await asyncio.to_thread(self._update, updated)
        self._metrics.increment("flags_reassigned" if was_assigned else "flags_assigned")
        return FlagResult(flag=updated)

    # ------------------------------------------------------------- resolve / dismiss

    async def resolve_flag(self, request: ResolveFlagRequest, session_id: str) -> FlagResult:
        """§4: an actual fix was applied. When `edit_field` is set, the fix is written
        through `edit_entry_point`'s own Persistence seam *before* the flag is marked
        resolved; a failed write leaves the flag unchanged (§4.3)."""
        return await self._settle(
            request.flag_id,
            session_id,
            target_status=FlagStatus.RESOLVED,
            resolution_note=request.resolution_note,
            operation_key="flag_resolved",
            counter="flags_resolved",
            edit_field=request.edit_field,
            edit_new_value=request.edit_new_value,
        )

    async def dismiss_flag(self, request: DismissFlagRequest, session_id: str) -> FlagResult:
        """§4: a confirmed false positive. A pure status transition — never carries an edit,
        because there is nothing to fix."""
        return await self._settle(
            request.flag_id,
            session_id,
            target_status=FlagStatus.DISMISSED,
            resolution_note=request.reason,
            operation_key="flag_dismissed",
            counter="flags_dismissed",
            edit_field=None,
            edit_new_value=None,
        )

    async def _settle(
        self,
        flag_id: str,
        session_id: str,
        *,
        target_status: FlagStatus,
        resolution_note: str,
        operation_key: str,
        counter: str,
        edit_field: str | None,
        edit_new_value: str | None,
    ) -> FlagResult:
        resolved = await self._role_resolver.resolve(session_id)
        actor_user_id = resolved[0] if resolved else "unresolved-session"
        role = resolved[1] if resolved else None

        flag = await self._get(flag_id)
        if flag is None:
            exc = UnknownFlag(flag_id)
            await self._record_attempt(actor_user_id, None, str(exc))
            return FlagResult(error_code=code_for(exc), error_detail=str(exc))

        if resolved is None or role not in RESOLVER_ROLES:
            self._metrics.increment("resolutions_denied_role")
            exc = RoleForbidden()
            await self._record_attempt(actor_user_id, flag, str(exc))
            return FlagResult(error_code=code_for(exc), error_detail=str(exc))

        if not can_transition(flag.status, target_status):
            self._metrics.increment("invalid_transitions_rejected")
            exc = InvalidStageTransition(
                f"{flag.flag_id!r} cannot move from {flag.status.value!r} to "
                f"{target_status.value!r}"
            )
            await self._record_attempt(actor_user_id, flag, str(exc))
            return FlagResult(error_code=code_for(exc), error_detail=str(exc))

        if not _can_act(flag, actor_user_id, role):
            self._metrics.increment("resolutions_denied_ownership")
            exc = OwnershipDenied(
                f"{actor_user_id!r} (role {role!r}) may not act on {flag.flag_id!r}, "
                f"assigned to {flag.assigned_to!r}"
            )
            await self._record_attempt(actor_user_id, flag, str(exc))
            return FlagResult(error_code=code_for(exc), error_detail=str(exc))

        if edit_field:
            write = await self._edit_gateway.apply_edit(
                flag.user_id, flag.receipt_id, edit_field, edit_new_value or "", actor_user_id
            )
            if not write.ok:
                self._metrics.increment("edit_writes_unavailable")
                exc = EditWriteFailed(write.error_detail or "the edit gateway refused the write")
                await self._record_attempt(actor_user_id, flag, str(exc))
                return FlagResult(error_code=code_for(exc), error_detail=str(exc))
            self._metrics.increment("edit_writes_applied")

        updated = replace(
            flag,
            status=target_status,
            assigned_to=flag.assigned_to or actor_user_id,
            resolved_at=utcnow(),
            resolved_by=actor_user_id,
            resolution_note=resolution_note,
        )
        await asyncio.to_thread(self._update, updated)
        self._metrics.increment(counter)

        outcome = await self._audit.record(
            PROPOSED_AUDIT_OPERATIONS[operation_key],
            actor_user_id,
            target_user_id=flag.user_id,
            reason=resolution_note or None,
            details={"flag_id": flag.flag_id, "flag_type": flag.flag_type, "receipt_id": flag.receipt_id},
        )
        self._metrics.increment(
            "audit_records_written" if outcome.recorded else "audit_records_degraded"
        )
        return FlagResult(flag=updated)

    async def _record_attempt(self, actor_user_id: str, flag: Flag | None, detail: str) -> None:
        """A refused attempt is still a privileged action worth a durable trace (task's own
        explicit requirement) — an unauthorized attempt that leaves no record is exactly the
        kind of thing `docs/PRINCIPLES.md` §4.3 says must be surfaced, not swallowed."""
        outcome = await self._audit.record(
            PROPOSED_AUDIT_OPERATIONS["flag_resolution_refused"],
            actor_user_id,
            target_user_id=flag.user_id if flag else None,
            reason=detail,
            details={"flag_id": flag.flag_id if flag else "", "outcome": "refused"},
        )
        self._metrics.increment(
            "audit_records_written" if outcome.recorded else "audit_records_degraded"
        )

    # ---------------------------------------------------------------------------- read

    async def get_flag(self, flag_id: str) -> Flag | None:
        return await self._get(flag_id)

    async def list_flags(self, query: ListFlagsQuery) -> ListFlagsResult:
        try:
            flags = await asyncio.to_thread(self._list, query)
        except sqlite3.DatabaseError as exc:
            return ListFlagsResult(error_code="STORE_UNAVAILABLE", error_detail=str(exc))
        return ListFlagsResult(flags=flags, total_matching=len(flags))

    # ---------------------------------------------------------------------- blocking half

    def _insert(self, flag: Flag) -> None:
        self._conn.execute("BEGIN")
        self._conn.execute(
            "INSERT INTO flags (flag_id, flag_type, user_id, receipt_id, status, created_by,"
            " created_at, assigned_to, resolved_at, resolved_by, resolution_note, payload)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            flag_to_insert_row(flag),
        )
        self._conn.commit()

    def _update(self, flag: Flag) -> None:
        from .db import UPDATE_SQL, to_storage_ts

        self._conn.execute(
            UPDATE_SQL,
            (
                flag.status.value,
                flag.assigned_to,
                to_storage_ts(flag.resolved_at) if flag.resolved_at else None,
                flag.resolved_by,
                flag.resolution_note,
                flag.flag_id,
            ),
        )
        self._conn.commit()

    def _get(self, flag_id: str):
        async def _run() -> Flag | None:
            row = await asyncio.to_thread(
                lambda: self._conn.execute(
                    "SELECT * FROM flags WHERE flag_id = ?", (flag_id,)
                ).fetchone()
            )
            return row_to_flag(row) if row is not None else None

        return _run()

    def _list(self, query: ListFlagsQuery) -> tuple[Flag, ...]:
        clauses: list[str] = []
        params: list = []
        if query.statuses:
            clauses.append(f"status IN ({','.join('?' * len(query.statuses))})")
            params.extend(s.value for s in query.statuses)
        if query.flag_type:
            clauses.append("flag_type = ?")
            params.append(query.flag_type)
        if query.receipt_id:
            clauses.append("receipt_id = ?")
            params.append(query.receipt_id)
        if query.assigned_to:
            clauses.append("assigned_to = ?")
            params.append(query.assigned_to)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, query.limit or 100)
        rows = self._conn.execute(
            f"SELECT * FROM flags{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            [*params, limit, max(0, query.offset)],
        ).fetchall()
        return tuple(row_to_flag(r) for r in rows)


__all__ = ["FlagStore", "can_transition", "new_flag_id"]

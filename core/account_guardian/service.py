"""The `AccountGuardianService` gRPC servicer — thin by design (deep-dive §2's own note that
`service.py` "delegates everything").

Every real decision lives in `devices.py`, `account_recovery.py`, `sso_linking.py`,
`privacy/*.py`, and `consent.py`. This file translates protobuf messages to and from those
modules' contract types and does exactly one more thing none of them can do for themselves:
**resolve the caller's own identity.**

**Auth's raise-loudly carve-out crosses into this file, and only this file** (with one
exception, noted at `ApproveRecovery`/`RejectRecovery`/`CompleteRecovery`/
`UpdateRecoveryChecklist` below). `_authenticate()` calls `gateways.SessionGateway.validate()`
for the caller's own `session_id` and lets `core.auth.errors.SessionInvalid`/`SessionExpired`
propagate into `context.abort(UNAUTHENTICATED, ...)` — the identical shape
`core/auth/service.py` uses for its own `AuthFailure` — rather than swallowing it into an
`error_code` field a caller could forget to check (`docs/PRINCIPLES.md` §4.1). Everything
*inside* `devices.py` et al. that looks up a *target* resource (a session id being revoked,
a case id being resolved) is ordinary data, because that is a lookup, not resolving who is
making the request.

`RequestAccountRecovery` is the one RPC with no `session_id` at all — a user filing it may,
by definition, have lost every authentication method they had (deep-dive §5).

Generated stubs are imported lazily inside every method and inside `serve()`, exactly as
`core/logs/service.py` and `core/health/service.py` both do, so this package stays
importable — and its tests meaningful — on an interpreter with no `grpcio` wheel yet.
"""

from __future__ import annotations

from datetime import datetime

import grpc

from . import account_recovery, consent, devices, sso_linking
from .contracts import (
    AuthMethod,
    ConsentDocumentType,
    RecoveryVerificationChecklist,
    Role,
)
from .errors import E_INVALID_REQUEST
from .gateways import (
    AuditGateway,
    BillingGateway,
    GrpcAuditGateway,
    GrpcSessionGateway,
    NoBillingConfiguredGateway,
    PersistenceGateway,
    SessionGateway,
    UnavailablePersistenceGateway,
)
from .metrics import AccountGuardianMetricsCollector
from .privacy import deletion_request, export_request
from .store import AccountGuardianDatabase

DEFAULT_ADDRESS = "127.0.0.1:50062"


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _unix(value: datetime | None) -> int:
    return int(value.timestamp()) if value else 0


def _tri_to_optional_bool(value: int) -> bool | None:
    return {0: None, 1: True, 2: False}.get(value)


def _optional_bool_to_tri(value: bool | None) -> int:
    if value is None:
        return 0
    return 1 if value else 2


def _parse_lost_method(raw: str) -> tuple[AuthMethod | None, str]:
    """Empty means unspecified. Anything else must be one of Auth's own four methods — a
    typo here should not silently become "no method named", which would make a real recovery
    case harder for staff to triage."""
    if not raw:
        return None, ""
    try:
        return AuthMethod(raw), ""
    except ValueError:
        return None, f"{raw!r} is not one of Auth's four methods (sso, passkey, email, sms)"


class AccountGuardianServicer:
    """Implements `AccountGuardianService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        *,
        session_gateway: SessionGateway | None = None,
        audit_gateway: AuditGateway | None = None,
        persistence_gateway: PersistenceGateway | None = None,
        billing_gateway: BillingGateway | None = None,
        db: AccountGuardianDatabase | None = None,
        metrics: AccountGuardianMetricsCollector | None = None,
    ) -> None:
        self._sessions = session_gateway or GrpcSessionGateway()
        self._audit = audit_gateway or GrpcAuditGateway()
        self._persistence = persistence_gateway or UnavailablePersistenceGateway()
        self._billing = billing_gateway or NoBillingConfiguredGateway()
        self._db = db or AccountGuardianDatabase()
        self._metrics = metrics or AccountGuardianMetricsCollector()

    # ------------------------------------------------------------- authentication
    async def _authenticate(self, context, session_id: str):
        """Resolve the caller. Raises `core.auth.errors.SessionInvalid`/`SessionExpired`
        straight into `context.abort` — Auth's own carve-out, reused rather than
        reinvented (`docs/PRINCIPLES.md` §4.1, this package's own `errors.py`)."""
        from core.auth.errors import AuthFailure

        try:
            return await self._sessions.validate(session_id)
        except AuthFailure as exc:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, f"{exc.error.value}: {exc.detail}")
            return None  # pragma: no cover - abort() raises; unreachable in real grpc.aio

    async def _authenticate_staff(self, context, session_id: str):
        """The reviewer-identity gate every recovery-resolution RPC needs: a fresh session,
        held by a staff or owner role — never a client role rubber-stamping their own case,
        and never a caller-asserted `reviewer_user_id` string (`docs/PRINCIPLES.md` §4.2)."""
        caller = await self._authenticate(context, session_id)
        if caller is None:
            return None  # pragma: no cover - _authenticate already aborted
        if caller.role not in (Role.STAFF, Role.OWNER):
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED,
                f"role {caller.role.value!r} may not resolve a recovery case",
            )
            return None  # pragma: no cover
        return caller

    # ------------------------------------------------------------------ devices
    async def ListSessions(self, request, context):
        from .generated import account_guardian_pb2 as pb

        caller = await self._authenticate(context, request.session_id)
        if caller is None:
            return pb.ListSessionsResponse()
        result = await devices.list_sessions(self._sessions, caller.user_id, request.session_id)
        self._metrics.increment("devices_listed")
        return pb.ListSessionsResponse(
            devices=[
                pb.DeviceSessionMessage(
                    session_id=d.session_id, created_at=_iso(d.created_at),
                    last_seen_at=_iso(d.last_seen_at), user_agent_summary=d.user_agent_summary,
                    is_current=d.is_current,
                )
                for d in result.devices
            ],
            error_code=result.error or "", error_detail=result.error_detail,
        )

    async def RevokeSession(self, request, context):
        from .generated import account_guardian_pb2 as pb

        caller = await self._authenticate(context, request.session_id)
        if caller is None:
            return pb.RevokeResponse()
        result = await devices.revoke_device(
            self._sessions, self._audit, caller.user_id, request.target_session_id
        )
        self._metrics.increment("devices_revoked", int(result.revoked))
        if not result.audit_recorded:
            self._metrics.increment("audit_write_failures")
        return pb.RevokeResponse(
            revoked=result.revoked, sessions_revoked=result.sessions_revoked,
            error_code=result.error or "", error_detail=result.error_detail,
            audit_recorded=result.audit_recorded, audit_error=result.audit_error,
        )

    async def RevokeAllSessions(self, request, context):
        from .generated import account_guardian_pb2 as pb

        caller = await self._authenticate(context, request.session_id)
        if caller is None:
            return pb.RevokeResponse()
        result = await devices.revoke_all_devices(self._sessions, self._audit, caller.user_id)
        self._metrics.increment("all_devices_revoked_calls")
        if not result.audit_recorded:
            self._metrics.increment("audit_write_failures")
        return pb.RevokeResponse(
            revoked=result.revoked, sessions_revoked=result.sessions_revoked,
            error_code=result.error or "", error_detail=result.error_detail,
            audit_recorded=result.audit_recorded, audit_error=result.audit_error,
        )

    # ------------------------------------------------------------------ recovery
    @staticmethod
    def _recovery_to_wire(result, pb):
        request = result.request
        if request is None:
            return pb.RecoveryResponse(error_code=result.error or "", error_detail=result.error_detail)
        checklist = request.checklist
        return pb.RecoveryResponse(
            request_id=request.request_id, user_id=request.user_id,
            requested_at=_iso(request.requested_at), stage=request.stage.value,
            lost_method=(request.lost_method.value if request.lost_method else ""),
            knowledge_check_passed=checklist.knowledge_check_passed,
            knowledge_check_note=checklist.knowledge_check_note,
            recovery_contact_state=_optional_bool_to_tri(checklist.recovery_contact_verified),
            vouched_by_user_id=checklist.vouched_by_user_id or "",
            reviewed_by=request.reviewed_by or "", resolved_at=_iso(request.resolved_at),
            notes=request.notes, error_code=result.error or "", error_detail=result.error_detail,
            audit_recorded=result.audit_recorded, audit_error=result.audit_error,
        )

    async def RequestAccountRecovery(self, request, context):
        from .generated import account_guardian_pb2 as pb

        method, detail = _parse_lost_method(request.lost_method)
        if detail:
            return pb.RecoveryResponse(error_code=E_INVALID_REQUEST, error_detail=detail)
        result = await account_recovery.create_request(self._db, request.user_id, method)
        self._metrics.increment("recovery_requests_created")
        return self._recovery_to_wire(result, pb)

    async def UpdateRecoveryChecklist(self, request, context):
        from .generated import account_guardian_pb2 as pb

        if await self._authenticate_staff(context, request.session_id) is None:
            return pb.RecoveryResponse()
        checklist = RecoveryVerificationChecklist(
            knowledge_check_passed=request.knowledge_check_passed,
            knowledge_check_note=request.knowledge_check_note,
            recovery_contact_verified=_tri_to_optional_bool(request.recovery_contact_state),
            vouched_by_user_id=request.vouched_by_user_id or None,
        )
        result = await account_recovery.update_checklist(self._db, request.request_id, checklist)
        return self._recovery_to_wire(result, pb)

    async def ApproveRecovery(self, request, context):
        from .generated import account_guardian_pb2 as pb

        caller = await self._authenticate_staff(context, request.session_id)
        if caller is None:
            return pb.RecoveryResponse()
        result = await account_recovery.approve(
            self._db, self._audit, request.request_id, caller.user_id, request.reason
        )
        if result.request is not None:
            self._metrics.increment("recovery_approved")
        if not result.audit_recorded:
            self._metrics.increment("audit_write_failures")
        return self._recovery_to_wire(result, pb)

    async def RejectRecovery(self, request, context):
        from .generated import account_guardian_pb2 as pb

        caller = await self._authenticate_staff(context, request.session_id)
        if caller is None:
            return pb.RecoveryResponse()
        result = await account_recovery.reject(
            self._db, self._audit, request.request_id, caller.user_id, request.reason
        )
        if result.request is not None:
            self._metrics.increment("recovery_rejected")
        return self._recovery_to_wire(result, pb)

    async def CompleteRecovery(self, request, context):
        from .generated import account_guardian_pb2 as pb

        caller = await self._authenticate_staff(context, request.session_id)
        if caller is None:
            return pb.RecoveryResponse()
        result = await account_recovery.complete(
            self._db, self._audit, request.request_id, caller.user_id, request.notes
        )
        if result.request is not None:
            self._metrics.increment("recovery_completed")
        return self._recovery_to_wire(result, pb)

    async def CancelRecovery(self, request, context):
        from .generated import account_guardian_pb2 as pb

        result = await account_recovery.cancel(self._db, request.request_id, request.acting_user_id)
        if result.request is not None and result.error is None:
            self._metrics.increment("recovery_cancelled")
        return self._recovery_to_wire(result, pb)

    async def GetRecovery(self, request, context):
        from .generated import account_guardian_pb2 as pb
        from .contracts import RecoveryResult

        found = await account_recovery.get(self._db, request.request_id)
        return self._recovery_to_wire(RecoveryResult(request=found), pb)

    async def ListRecoveryForUser(self, request, context):
        from .generated import account_guardian_pb2 as pb
        from .contracts import RecoveryResult

        requests = await account_recovery.list_for_user(self._db, request.user_id)
        return pb.ListRecoveryResponse(
            requests=[self._recovery_to_wire(RecoveryResult(request=r), pb) for r in requests]
        )

    # ---------------------------------------------------------------- SSO link
    @staticmethod
    def _sso_to_wire(result, pb):
        request = result.request
        if request is None:
            return pb.SsoLinkResponse(error_code=result.error or "", error_detail=result.error_detail)
        return pb.SsoLinkResponse(
            request_id=request.request_id, user_id=request.user_id, provider=request.provider,
            requested_at=_iso(request.requested_at), stage=request.stage.value,
            completed_at=_iso(request.completed_at), error_code=result.error or "",
            error_detail=result.error_detail, audit_recorded=result.audit_recorded,
            audit_error=result.audit_error,
        )

    async def RequestSsoLink(self, request, context):
        from .generated import account_guardian_pb2 as pb

        caller = await self._authenticate(context, request.session_id)
        if caller is None:
            return pb.SsoLinkResponse()
        result = await sso_linking.request_link(
            self._db, self._audit, caller.user_id, request.provider, request.step_up_confirmed
        )
        if result.request is not None:
            self._metrics.increment("sso_link_requests")
        return self._sso_to_wire(result, pb)

    async def CancelSsoLink(self, request, context):
        from .generated import account_guardian_pb2 as pb

        result = await sso_linking.cancel(self._db, request.request_id, request.acting_user_id)
        return self._sso_to_wire(result, pb)

    # ------------------------------------------------------------------ export
    async def RequestDataExport(self, request, context):
        from .generated import account_guardian_pb2 as pb

        caller = await self._authenticate(context, request.session_id)
        if caller is None:
            return pb.ExportResponse()
        provider = request.provider_name or export_request.DATA_PORTABILITY_PROVIDER
        result = await export_request.request_export(
            self._db, self._audit, self._persistence, caller.user_id, provider
        )
        self._metrics.increment("export_requests")
        if not result.audit_recorded:
            self._metrics.increment("audit_write_failures")
        return self._export_to_wire(result, pb)

    async def GetExportStatus(self, request, context):
        from .generated import account_guardian_pb2 as pb

        result = await export_request.request_status(self._db, request.request_id)
        return self._export_to_wire(result, pb)

    @staticmethod
    def _export_to_wire(result, pb):
        request = result.request
        if request is None:
            return pb.ExportResponse(error_code=result.error or "", error_detail=result.error_detail)
        return pb.ExportResponse(
            request_id=request.request_id, user_id=request.user_id,
            requested_at=_iso(request.requested_at), status=request.status.value,
            export_logical_id=(request.export_blob_ref.logical_id if request.export_blob_ref else ""),
            error_code=result.error or "", error_detail=request.error_detail or result.error_detail,
            audit_recorded=result.audit_recorded, audit_error=result.audit_error,
        )

    # ---------------------------------------------------------------- deletion
    @staticmethod
    def _deletion_to_wire(result, pb):
        request = result.request
        if request is None:
            return pb.DeletionResponse(error_code=result.error or "", error_detail=result.error_detail)
        return pb.DeletionResponse(
            request_id=request.request_id, user_id=request.user_id,
            requested_at=_iso(request.requested_at), stage=request.stage.value,
            grace_period_ends_at_unix=_unix(request.grace_period_ends_at),
            completed_at_unix=_unix(request.completed_at), error_code=result.error or "",
            error_detail=result.error_detail, audit_recorded=result.audit_recorded,
            audit_error=result.audit_error,
        )

    async def RequestDeletion(self, request, context):
        from .generated import account_guardian_pb2 as pb

        caller = await self._authenticate(context, request.session_id)
        if caller is None:
            return pb.DeletionResponse()
        days = request.grace_period_days or deletion_request.DEFAULT_GRACE_PERIOD_DAYS
        result = await deletion_request.request_deletion(
            self._db, self._audit, self._billing, caller.user_id, days
        )
        if result.request is not None:
            self._metrics.increment("deletion_requests")
        if not result.audit_recorded:
            self._metrics.increment("audit_write_failures")
        return self._deletion_to_wire(result, pb)

    async def CancelDeletion(self, request, context):
        from .generated import account_guardian_pb2 as pb

        result = await deletion_request.cancel_deletion(
            self._db, self._audit, request.request_id, request.acting_user_id
        )
        if result.request is not None and result.error is None:
            self._metrics.increment("deletion_cancelled")
        return self._deletion_to_wire(result, pb)

    async def GetDeletionStatus(self, request, context):
        from .generated import account_guardian_pb2 as pb
        from .contracts import DeletionResult

        found = await deletion_request.get(self._db, request.request_id)
        if found is None:
            from .errors import NotFound

            return pb.DeletionResponse(
                error_code=NotFound.code, error_detail=f"no such request {request.request_id!r}"
            )
        return self._deletion_to_wire(DeletionResult(request=found), pb)

    # ----------------------------------------------------------------- consent
    async def GetCurrentPolicyVersion(self, request, context):
        from .generated import account_guardian_pb2 as pb

        try:
            doc_type = ConsentDocumentType(request.document_type)
        except ValueError:
            return pb.PolicyVersionResponse(published=False)
        version = await consent.current_version(self._db, doc_type)
        if version is None:
            return pb.PolicyVersionResponse(document_type=doc_type.value, published=False)
        return pb.PolicyVersionResponse(
            document_type=version.document_type.value, version=version.version,
            published_at=_iso(version.published_at), text_ref=version.text_ref,
            requires_reconsent=version.requires_reconsent, published=True,
        )

    async def RecordConsent(self, request, context):
        from .generated import account_guardian_pb2 as pb

        try:
            doc_type = ConsentDocumentType(request.document_type)
        except ValueError:
            return pb.ConsentResponse(
                error_code=E_INVALID_REQUEST,
                error_detail=f"{request.document_type!r} is not a known document type",
            )
        await consent.record_consent(
            self._db, request.user_id, doc_type, request.document_version,
            request.ip_address or None,
        )
        self._metrics.increment("consent_recorded")
        result = await consent.check_consent(self._db, request.user_id, doc_type)
        return pb.ConsentResponse(
            has_valid_consent=result.has_valid_consent,
            current_version=(result.current_version.version if result.current_version else ""),
        )


def serve(
    address: str = DEFAULT_ADDRESS,
    *,
    session_gateway: SessionGateway | None = None,
    audit_gateway: AuditGateway | None = None,
    persistence_gateway: PersistenceGateway | None = None,
    billing_gateway: BillingGateway | None = None,
    db: AccountGuardianDatabase | None = None,
) -> grpc.aio.Server:
    """Start the service. Returns the running server so a caller can stop it.

    Pass a `:0` port to bind an ephemeral one; the bound address is attached as
    `bound_address`. Worth having rather than a fixed port: Windows reserves scattered
    ranges in the 50000s, so a hard-coded high port is not reliably bindable everywhere.
    """
    from .generated import account_guardian_pb2_grpc as pb_grpc

    servicer = AccountGuardianServicer(
        session_gateway=session_gateway, audit_gateway=audit_gateway,
        persistence_gateway=persistence_gateway, billing_gateway=billing_gateway, db=db,
    )
    server = grpc.aio.server()
    pb_grpc.add_AccountGuardianServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = serve(addr)
        await srv.start()
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"AccountGuardianService listening on {srv.bound_address}", file=sys.stderr)
        print(f"running under: {sys.executable} ({sys.version.split()[0]})", file=sys.stderr)
        await srv.wait_for_termination()

    asyncio.run(_main())


__all__ = ["DEFAULT_ADDRESS", "AccountGuardianServicer", "serve"]

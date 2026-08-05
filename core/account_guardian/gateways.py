"""External-service adapters (`docs/PRINCIPLES.md` §1.3) — not in the deep-dive's §2 layout.

Account Guardian has no compute of its own (deep-dive §8.1: "a thin orchestration layer over
other APIs' primitives"); everything it does is a call to a Core API running in a *different*
OS process (`docs/PROCESS_TOPOLOGY.md` §1). Three real dependencies, three small Protocols,
one adapter each — the same "external dependency behind one small internal interface, never
hardcoded into scattered call sites" discipline every other pluggable capability in this repo
follows:

- `SessionGateway` -> Auth & Tenancy's `AuthService` (`devices.py`, `account_recovery.py`,
  `sso_linking.py`, `consent.py` all need to resolve, revoke, or enumerate sessions).
- `PersistenceGateway` -> Persistence's Export Framework and, eventually, an account-erasure
  path (`privacy/export_request.py`, `privacy/deletion_request.py`).
- `BillingGateway` -> Billing API's subscription-clearance check
  (`privacy/deletion_request.py`, deep-dive §6.3).

**Three real, current cross-API gaps live in this file, each documented at its raise site
rather than only here** — flagged deliberately (`docs/PRINCIPLES.md` §4.3: surface a genuine
conflict, never guess past it) rather than worked around with a guess:

1. Auth's own `auth.proto` has no RPC that lists a user's active sessions. `ValidateSession`
   and `RevokeSession` (by id, or all-for-user) are all it exposes. `devices.py` needs to
   *list* devices before a user can choose one to revoke, and that RPC does not exist yet.
2. Persistence has not generated a gRPC surface for `persistence.proto` at all yet — no
   `core/persistence/generated/` package exists. `GenerateExport` is specified in the
   `.proto` file itself but nothing serves it over gRPC today.
3. Billing API (`core/billing/`) has no implementation in this build at all.

Every adapter below fails toward the *documented, inspectable* default rather than a silent
guess: a capability gap raises `CapabilityMissing` with the specific citation above, and a
transport failure raises `DependencyUnavailable` — never a swallowed exception that lets a
caller believe an action succeeded when the dependency was never actually reached.

Generated gRPC stubs are imported lazily inside each method that needs them, exactly as
`core/logs/service.py` does — this module, and everything that imports it, stays importable
on an interpreter with no `grpcio` wheel yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from core.auth.errors import SessionExpired, SessionInvalid

from .contracts import CallerSession, ExportOutcome, Role

DEFAULT_AUTH_ADDRESS = "127.0.0.1:50056"
DEFAULT_PERSISTENCE_ADDRESS = "127.0.0.1:50052"


@dataclass(frozen=True)
class RawSession:
    """The fuller session shape `devices.py` needs to build a `DeviceSession` — what a real
    `ListSessionsForUser` RPC would return, if Auth exposed one (gap #1 above)."""

    session_id: str
    user_id: str
    created_at: datetime
    last_seen_at: datetime


@runtime_checkable
class SessionGateway(Protocol):
    """What Account Guardian needs from Auth & Tenancy. Structural typing — a concrete
    adapter never needs to inherit from this."""

    async def validate(self, session_id: str) -> CallerSession:
        """Resolve a session. Raises `core.auth.errors.SessionInvalid` / `SessionExpired`
        exactly as `SessionStore.validate()` does — Auth's own carve-out
        (`docs/PRINCIPLES.md` §4.1), reused rather than reinvented (see this package's own
        `errors.py`). Never returns a value for a session that does not check out."""
        ...

    async def revoke(self, session_id: str) -> bool: ...

    async def revoke_all_for_user(self, user_id: str) -> int: ...

    async def list_sessions(self, user_id: str) -> tuple[RawSession, ...]:
        """Raises `errors.CapabilityMissing` against every implementation in this file
        today — gap #1 above. Declared here anyway, and not simply omitted from the
        Protocol, because this is the shape Account Guardian needs regardless of whether
        Auth can serve it yet; the alternative (leaving it out) would make the gap
        invisible in the one place a future session would look to find it."""
        ...


def _map_validate_failure(detail: str) -> SessionInvalid | SessionExpired:
    """Reconstruct which of Auth's own two carve-out exceptions a wire failure represents.

    Auth's `service.py._abort` formats every `AuthFailure` as `f"{exc.error.value}: ...`
    before aborting the RPC (`core/auth/service.py`) — the prefix is the one piece of
    structure this client can reliably parse back out of a `grpc.RpcError`'s detail string.
    Anything that does not match is treated as `SessionInvalid`, the more restrictive of the
    two: an ambiguous failure denies rather than assumes the milder case
    (`docs/PRINCIPLES.md` §4.2).
    """
    if detail.startswith("session_expired"):
        return SessionExpired(detail)
    return SessionInvalid(detail)


class GrpcSessionGateway:
    """The real adapter, once Auth is reachable over gRPC. Implements `SessionGateway`."""

    def __init__(self, address: str = DEFAULT_AUTH_ADDRESS, channel=None) -> None:
        self._address = address
        self._channel = channel

    def _get_channel(self):
        import grpc

        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._address)
        return self._channel

    async def validate(self, session_id: str) -> CallerSession:
        import grpc

        from core.auth.generated import auth_pb2 as pb
        from core.auth.generated import auth_pb2_grpc as pb_grpc

        stub = pb_grpc.AuthServiceStub(self._get_channel())
        try:
            resp = await stub.ValidateSession(pb.ValidateSessionRequest(session_id=session_id))
        except grpc.RpcError as exc:
            code = exc.code() if hasattr(exc, "code") else None
            detail = exc.details() if hasattr(exc, "details") else str(exc)
            if code in (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED):
                raise _map_validate_failure(detail or "") from exc
            # Anything else (UNAVAILABLE, DEADLINE_EXCEEDED, UNKNOWN...) is a transport
            # failure, not a verdict about the session. §4.2 fail-closed: treated the same
            # as an invalid session rather than as "maybe fine" — an unresolvable security
            # check must deny, never silently pass.
            raise SessionInvalid(f"auth service unreachable: {detail}") from exc
        return CallerSession(session_id=resp.session_id, user_id=resp.user_id, role=Role(resp.role))

    async def revoke(self, session_id: str) -> bool:
        import grpc

        from core.auth.generated import auth_pb2 as pb
        from core.auth.generated import auth_pb2_grpc as pb_grpc
        from .errors import DependencyUnavailable

        stub = pb_grpc.AuthServiceStub(self._get_channel())
        try:
            resp = await stub.RevokeSession(pb.RevokeSessionRequest(session_id=session_id))
        except grpc.RpcError as exc:
            # Deep-dive §11's own named testing hook: a revocation during Auth being briefly
            # unavailable must surface as a visible failure, never a silent no-op the caller
            # would read as "the device was logged out".
            raise DependencyUnavailable(f"auth service unreachable: {exc}") from exc
        return bool(resp.revoked)

    async def revoke_all_for_user(self, user_id: str) -> int:
        import grpc

        from core.auth.generated import auth_pb2 as pb
        from core.auth.generated import auth_pb2_grpc as pb_grpc
        from .errors import DependencyUnavailable

        stub = pb_grpc.AuthServiceStub(self._get_channel())
        try:
            resp = await stub.RevokeSession(
                pb.RevokeSessionRequest(all_for_user=True, user_id=user_id)
            )
        except grpc.RpcError as exc:
            raise DependencyUnavailable(f"auth service unreachable: {exc}") from exc
        return int(resp.sessions_revoked)

    async def list_sessions(self, user_id: str) -> tuple[RawSession, ...]:
        from .errors import CapabilityMissing

        raise CapabilityMissing(
            "Auth's AuthService has no session-listing RPC (auth.proto defines only "
            "ValidateSession and RevokeSession). Device listing needs one added there "
            "before this adapter can implement it — see this package's CLAUDE.md."
        )


@runtime_checkable
class PersistenceGateway(Protocol):
    """What Account Guardian needs from Persistence's Export Framework, and eventually its
    account-erasure path (deep-dive §6.2, §6.3)."""

    async def generate_export(
        self, user_id: str, provider_name: str, params_json: str = "{}"
    ) -> ExportOutcome: ...

    async def erase_account(self, user_id: str) -> "EraseOutcome": ...


class UnavailablePersistenceGateway:
    """The honest default: gap #2 above. Persistence's own `.proto` specifies
    `GenerateExport`, but no `core/persistence/generated/` package exists to serve it, so
    there is nothing on the other end of a channel to this address today. Every call
    degrades to a clearly-labeled unavailable result rather than attempting a connection
    that cannot succeed (`docs/PRINCIPLES.md` §4.4)."""

    _DETAIL = (
        "Persistence has not generated a gRPC servicer for persistence.proto yet (no "
        "core/persistence/generated/ package exists); GenerateExport cannot be reached "
        "until that lands — see this package's CLAUDE.md."
    )

    async def generate_export(
        self, user_id: str, provider_name: str, params_json: str = "{}"
    ) -> ExportOutcome:
        from .errors import E_CAPABILITY_MISSING

        return ExportOutcome(ok=False, error=E_CAPABILITY_MISSING, error_detail=self._DETAIL)

    async def erase_account(self, user_id: str):
        from .contracts import EraseOutcome
        from .errors import E_CAPABILITY_MISSING

        return EraseOutcome(ok=False, error=E_CAPABILITY_MISSING, error_detail=self._DETAIL)


@dataclass(frozen=True)
class BillingClearance:
    clear: bool
    detail: str = ""


@runtime_checkable
class BillingGateway(Protocol):
    """What a deletion needs from Billing (deep-dive §6.3): is this account's subscription
    state clean, or does deletion need to wait in `BILLING_HOLD`."""

    async def resolve_deletion_clearance(self, user_id: str) -> BillingClearance: ...


class NoBillingConfiguredGateway:
    """The default when no Billing API is wired in — true for every installation in this
    build, since `core/billing/` has no implementation yet (gap #3 above).

    **Deliberately returns `clear=True`, not a fail-closed denial.** Billing clearance is a
    business-process gate, not a security check: the deep-dive's own reasoning (§6.3) is
    that a deletion should not proceed *only while a real subscription still needs
    resolving*. An install with no billing subsystem at all — every self-hosted install
    today, and every installation in this build — has nothing to resolve, the same way a
    disabled SMS provider degrades that one login method rather than blocking login
    entirely (`docs/PRINCIPLES.md` §4.4). This is not the §4.2 fail-closed case: that clause
    governs security checks (a session, a role, a content scan), not a domain process gate
    with no configured backend at all.

    **This default is not safe for DOMTRI's own hosted multi-tenant deployment once Billing
    API exists.** A hosted install running against this default would let every deletion
    request skip subscription resolution silently — not silently in the sense of hiding it
    (the detail string here is carried into every `DeletionRequest` this gateway touches),
    but silently in the sense that nobody looking only at "did deletion succeed" would
    notice billing was never actually checked. Wiring a real `BillingGateway` is a
    precondition for hosted go-live, not an optional enhancement — see this package's
    CLAUDE.md and the final report this gap was raised in.
    """

    _DETAIL = (
        "no Billing API is wired into this Account Guardian instance; treated as nothing to "
        "resolve. Correct for a self-hosted/no-subscription install. DOMTRI's hosted "
        "multi-tenant deployment MUST inject a real BillingGateway once Billing API exists."
    )

    async def resolve_deletion_clearance(self, user_id: str) -> BillingClearance:
        return BillingClearance(clear=True, detail=self._DETAIL)


@dataclass(frozen=True)
class AuditOutcome:
    """What recording a privileged action with Audit actually produced. Deliberately
    separate from whatever action triggered it (`RevokeResult`, `RecoveryResult`, ...): an
    action can succeed while its audit write degrades, and the two must stay tellable apart
    the same way `core.audit.contracts.RecordResult` keeps a degraded mirror distinct from a
    failed primary write."""

    recorded: bool
    event_id: str = ""
    error: str = ""
    error_detail: str = ""


@runtime_checkable
class AuditGateway(Protocol):
    async def record(
        self,
        operation: str,
        actor_user_id: str,
        *,
        target_user_id: str | None = None,
        reason: str | None = None,
        details: dict | None = None,
    ) -> AuditOutcome: ...


#: **A real, current cross-API gap, not a bug in this package.** Audit's own
#: `contracts.PRIVILEGED_ACTIONS` (`core/audit/contracts.py`) is a deliberately *closed*
#: vocabulary — `AuditWriter.record_action()` refuses any operation name not registered
#: there, and the wire `RecordAction` RPC only ever exposes that same operation-name path,
#: never a raw `AuditEvent`. Of everything this package needs to record, only
#: `"account_recovery_approve"` (-> `ActionType.ACCOUNT_RECOVERY_APPROVED`) is registered
#: today. The operation names below for device revocation, SSO provider changes, and
#: export/deletion request lifecycle events are this package's own documented *proposal*
#: for what Audit should register next — calling `GrpcAuditGateway.record()` with one of
#: them against today's real Audit process returns `recorded=False`,
#: `error="UNKNOWN_ACTION"`, which every caller in this package surfaces on its own result
#: (`audit_recorded`/`audit_error`) rather than silently swallowing
#: (`docs/PRINCIPLES.md` §4.3). This package's `CLAUDE.md` and the implementation report
#: both flag it; `core/audit/contracts.py` is out of scope for this package to edit.
PROPOSED_AUDIT_OPERATIONS: dict[str, str] = {
    "device_revoked": "account_guardian_device_revoked",
    "all_devices_revoked": "account_guardian_all_devices_revoked",
    "sso_provider_change_requested": "account_guardian_sso_provider_change_requested",
    "export_requested": "account_guardian_export_requested",
    "deletion_requested": "account_guardian_deletion_requested",
    "deletion_cancelled": "account_guardian_deletion_cancelled",
    "deletion_completed": "account_guardian_deletion_completed",
    "recovery_rejected": "account_guardian_recovery_rejected",
    "recovery_completed": "account_guardian_recovery_completed",
    #: The one operation name that genuinely exists in Audit's own registry today.
    "recovery_approved": "account_recovery_approve",
}


class GrpcAuditGateway:
    """Implements `AuditGateway` against the real `AuditService` (`core/audit/audit.proto`).

    Unlike `UnavailablePersistenceGateway`, this one is real end to end: Audit's own gRPC
    surface and generated stubs already exist (`core/audit/generated/`). The gap is not
    reachability, it is the closed operation vocabulary documented at
    `PROPOSED_AUDIT_OPERATIONS` above — this adapter still makes the call and reports
    exactly what Audit says, rather than pretending success for an operation name Audit
    does not recognise yet.
    """

    def __init__(self, address: str = "127.0.0.1:50058", channel=None) -> None:
        self._address = address
        self._channel = channel

    def _get_channel(self):
        import grpc

        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._address)
        return self._channel

    async def record(
        self,
        operation: str,
        actor_user_id: str,
        *,
        target_user_id: str | None = None,
        reason: str | None = None,
        details: dict | None = None,
    ) -> AuditOutcome:
        import json

        import grpc

        from core.audit.generated import audit_pb2 as pb
        from core.audit.generated import audit_pb2_grpc as pb_grpc

        stub = pb_grpc.AuditServiceStub(self._get_channel())
        try:
            resp = await stub.RecordAction(
                pb.RecordActionRequest(
                    operation=operation,
                    actor_user_id=actor_user_id,
                    target_user_id=target_user_id or "",
                    reason=reason or "",
                    details_json=json.dumps(details or {}, default=str),
                )
            )
        except grpc.RpcError as exc:
            return AuditOutcome(recorded=False, error="DEPENDENCY_UNAVAILABLE", error_detail=str(exc))
        return AuditOutcome(
            recorded=resp.recorded, event_id=resp.event_id,
            error=resp.error_code, error_detail=resp.error_detail,
        )


__all__ = [
    "AuditGateway",
    "AuditOutcome",
    "BillingClearance",
    "BillingGateway",
    "DEFAULT_AUTH_ADDRESS",
    "DEFAULT_PERSISTENCE_ADDRESS",
    "GrpcAuditGateway",
    "GrpcSessionGateway",
    "NoBillingConfiguredGateway",
    "PROPOSED_AUDIT_OPERATIONS",
    "PersistenceGateway",
    "RawSession",
    "SessionGateway",
    "UnavailablePersistenceGateway",
]

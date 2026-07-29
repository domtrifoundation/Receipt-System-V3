"""External-service adapters (`docs/PRINCIPLES.md` §1.3) — not in the deep-dive's §2 layout,
added for the same reason `core/account_guardian/gateways.py` exists: this package is a thin
lifecycle layer over other APIs' own primitives (Architect's taxonomy, Audit's privileged-
action log, Notifications' inbox, Auth's session store, Persistence's write path), and each
of those five real dependencies gets its own small Protocol implementation here rather than
being reached for ad hoc inside `lifecycle.py`/`audit_screen.py`/`edit_entry_point.py`.

**Two of these are real, end to end, and three are honest, documented gaps** — the same split
account_guardian's own `gateways.py` states for its own dependencies:

- `GrpcSessionRoleResolver` -> Auth & Tenancy's real `AuthService.ValidateSession`
  (`core/auth/generated/` exists and is reachable). This is what makes "resolved server-side
  from the session, never a caller-asserted role" a real guarantee rather than a stub.
- `GrpcAuditRecorder` -> Audit's real `AuditService.RecordAction`
  (`core/audit/generated/` exists). The gap here is not reachability, it is Audit's own
  *closed* operation vocabulary (`core/audit/contracts.py::PRIVILEGED_ACTIONS`) — this
  package's own operations (`review_flag_resolved`, `review_flag_dismissed`) are not
  registered there yet, so a real call against today's Audit returns `recorded=False,
  error_code="UNKNOWN_ACTION"`, surfaced honestly rather than swallowed
  (`docs/PRINCIPLES.md` §4.3) — identical in shape to account_guardian's own
  `PROPOSED_AUDIT_OPERATIONS` gap.
- `GrpcFlagNotifier` -> Notifications' real `NotificationsService.Notify`
  (`core/notifications/generated/` exists, and `notifications.proto` itself names
  "Review/Flagging's new-flag creation" as a caller). No gap at all: `category` is an
  unvalidated string on that side, so there is nothing to register.
- `PermissiveFlagTypeValidator`/`RegistryFlagTypeValidator` -> Architect's registry. Real
  membership checking requires a live `DefinitionRegistry`-shaped object (Architect has no
  gRPC surface of its own yet — no `core/architect/generated/` exists), so the default is
  permissive (§4.4, not a security check) and `RegistryFlagTypeValidator` is the seam a
  caller composes with a real registry object at construction time.
- `UnavailablePersistenceWriteGateway` -> Persistence's normal write path. `persistence.proto`
  defines no field-level edit RPC and `core/persistence/generated/` does not exist at all
  (the identical gap account_guardian's own `UnavailablePersistenceGateway` documents) — every
  edit degrades to a clearly-labeled unavailable result rather than attempting a connection
  that cannot succeed.

Generated gRPC stubs are imported lazily inside each method that needs them, exactly as
`core/logs/service.py` and `core/account_guardian/gateways.py` do — this module, and
everything that imports it, stays importable on an interpreter with no `grpcio` wheel yet.
"""

from __future__ import annotations

from typing import Callable

from .contracts import AuditRecordOutcome, EditWriteResult, Flag

DEFAULT_AUTH_ADDRESS = "127.0.0.1:50056"
DEFAULT_AUDIT_ADDRESS = "127.0.0.1:50058"
DEFAULT_NOTIFICATIONS_ADDRESS = "127.0.0.1:50060"

#: This package's own documented *proposal* for what Audit should register next — see the
#: module docstring's own gap #2. Calling `GrpcAuditRecorder.record()` with one of these
#: against today's real Audit process returns `recorded=False, error_code="UNKNOWN_ACTION"`,
#: which `lifecycle.py` surfaces on `FlagResult`/audit-view results rather than swallowing.
PROPOSED_AUDIT_OPERATIONS: dict[str, str] = {
    "flag_resolved": "review_flagging_flag_resolved",
    "flag_dismissed": "review_flagging_flag_dismissed",
    "flag_resolution_refused": "review_flagging_flag_resolution_refused",
}


# ------------------------------------------------------------------ Architect (taxonomy)


class PermissiveFlagTypeValidator:
    """The default `FlagTypeValidator` (see `contracts.py`'s own docstring on why
    `flag_type` stays a plain string): accepts any non-empty code. Not a security check, so
    an unwired Architect registry degrades to "accept it" rather than to "reject it"
    (`docs/PRINCIPLES.md` §4.4) — the identical posture
    `core/notifications/inbox.py::PermissiveCategoryValidator` takes for `category`."""

    def is_known(self, flag_type: str) -> bool:
        return bool(flag_type and flag_type.strip())


class RegistryFlagTypeValidator:
    """Adapts a real Architect `DefinitionRegistry`-shaped object without importing Architect's
    own registry module from this package's business logic (`docs/PRINCIPLES.md` §1.3) — only
    `contracts.py`'s `ARCHITECT_FLAG_TYPE_KIND` is shared, since `contracts.py`-to-`contracts.py`
    is the one cross-package import this project's own layering allows.

    `knows` is injected by whatever holds the real registry (e.g.
    `core.architect.registry.read.DefinitionRegistry.knows`, partially applied against
    `ARCHITECT_FLAG_TYPE_KIND`) — the same "adapt without importing the other API's logic
    module" shape `core/logs/query.py::AuthBreakGlassChecker` uses for Auth's break-glass
    check.
    """

    def __init__(self, knows: Callable[[str], bool]) -> None:
        self._knows = knows

    def is_known(self, flag_type: str) -> bool:
        try:
            return bool(self._knows(flag_type))
        except Exception:  # noqa: BLE001 - not a security check; a broken checker degrades
            return False


# ------------------------------------------------------------------------- Auth (session/role)


class DenyAllSessions:
    """The fail-closed default (`docs/PRINCIPLES.md` §4.2): every session is unresolvable
    until a real resolver is wired in. An unresolvable session denies, it is never treated
    as a lesser role — there is no "assume client" fallback anywhere in this package."""

    async def resolve(self, session_id: str) -> tuple[str, str] | None:
        return None


class GrpcSessionRoleResolver:
    """Resolves `(user_id, role)` from Auth & Tenancy's real `ValidateSession` RPC.

    Unlike Persistence's gap, this one is real end to end: `core/auth/generated/` exists and
    `ValidateSession` is Auth's own highest-volume, already-implemented call. Any failure —
    an invalid/expired session, or the Auth process being unreachable — resolves to `None`,
    identical in spirit to `core/account_guardian/gateways.py::GrpcSessionGateway.validate`'s
    own fail-closed handling of the same RPC, except here a wire failure is swallowed into
    `None` rather than re-raised, since this package's own contract for this seam is "a role
    or nothing," never an exception a caller must catch.
    """

    def __init__(self, address: str = DEFAULT_AUTH_ADDRESS, channel=None) -> None:
        self._address = address
        self._channel = channel

    def _get_channel(self):
        import grpc

        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._address)
        return self._channel

    async def resolve(self, session_id: str) -> tuple[str, str] | None:
        if not session_id:
            return None
        import grpc

        from core.auth.generated import auth_pb2 as pb
        from core.auth.generated import auth_pb2_grpc as pb_grpc

        stub = pb_grpc.AuthServiceStub(self._get_channel())
        try:
            resp = await stub.ValidateSession(pb.ValidateSessionRequest(session_id=session_id))
        except grpc.RpcError:
            # Fail closed (§4.2): a transport failure is not distinguishable here from an
            # invalid session, and both must deny rather than one of them silently passing.
            return None
        if resp.error_code or not resp.user_id or not resp.role:
            return None
        return (resp.user_id, resp.role)


# --------------------------------------------------------------------------- Audit


class GrpcAuditRecorder:
    """Implements `contracts.AuditRecorder` against the real `AuditService`
    (`core/audit/audit.proto`). See the module docstring's own gap #2 — the operation
    vocabulary, not reachability, is what is missing today."""

    def __init__(self, address: str = DEFAULT_AUDIT_ADDRESS, channel=None) -> None:
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
    ) -> AuditRecordOutcome:
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
                    details_json=json.dumps(details or {}, default=str, sort_keys=True),
                )
            )
        except grpc.RpcError as exc:
            return AuditRecordOutcome(
                recorded=False, error_code="AUDIT_UNAVAILABLE", error_detail=str(exc)
            )
        return AuditRecordOutcome(
            recorded=resp.recorded,
            event_id=resp.event_id,
            error_code=resp.error_code,
            error_detail=resp.error_detail,
        )


# ------------------------------------------------------------------------ Notifications


class GrpcFlagNotifier:
    """Implements `contracts.FlagNotifier` against the real `NotificationsService`
    (`core/notifications/notifications.proto`, which names this exact call as a caller of
    `Notify`). Real end to end: no operation-vocabulary gap exists on this side, since
    `Notification.category` is deliberately an unvalidated string."""

    def __init__(self, address: str = DEFAULT_NOTIFICATIONS_ADDRESS, channel=None) -> None:
        self._address = address
        self._channel = channel

    def _get_channel(self):
        import grpc

        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._address)
        return self._channel

    async def notify_new_flag(self, flag: Flag) -> bool:
        import grpc

        from core.notifications.generated import notifications_pb2 as pb
        from core.notifications.generated import notifications_pb2_grpc as pb_grpc

        stub = pb_grpc.NotificationsServiceStub(self._get_channel())
        try:
            resp = await stub.Notify(
                pb.NotifyRequest(
                    user_id=flag.user_id,
                    category="review_flag_created",
                    title=f"New flag: {flag.flag_type}",
                    body=(
                        f"Receipt {flag.receipt_id} was flagged ({flag.flag_type}) by "
                        f"{flag.created_by}."
                    ),
                    reference=flag.flag_id,
                )
            )
        except grpc.RpcError:
            return False
        return bool(resp.ok)


class NullFlagNotifier:
    """A notifier that never sends — used where a caller deliberately does not want new-flag
    creation to attempt an outbound call (e.g. an offline batch import). Distinct from a
    transport failure: this is a configuration choice, not a degraded dependency."""

    async def notify_new_flag(self, flag: Flag) -> bool:
        return False


# -------------------------------------------------------------------------- Persistence


class UnavailablePersistenceWriteGateway:
    """The honest default: `persistence.proto` defines no field-level edit RPC and
    `core/persistence/generated/` does not exist at all — the identical gap
    `core/account_guardian/gateways.py::UnavailablePersistenceGateway` documents for
    `GenerateExport`. Every edit degrades to a clearly-labeled unavailable result rather than
    attempting a connection that cannot succeed (`docs/PRINCIPLES.md` §4.4) — and, per §4.3,
    a resolution that depended on this write never silently proceeds anyway; see
    `lifecycle.resolve`."""

    _DETAIL = (
        "Persistence has not generated a gRPC servicer for persistence.proto yet (no "
        "core/persistence/generated/ package exists), and persistence.proto itself defines "
        "no field-level edit RPC; ApplyEdit cannot be reached until both land — see this "
        "package's CLAUDE.md."
    )

    async def apply_edit(
        self, user_id: str, receipt_id: str, field: str, new_value: str, actor_user_id: str
    ) -> EditWriteResult:
        return EditWriteResult(ok=False, error_code="CAPABILITY_MISSING", error_detail=self._DETAIL)


__all__ = [
    "DEFAULT_AUDIT_ADDRESS",
    "DEFAULT_AUTH_ADDRESS",
    "DEFAULT_NOTIFICATIONS_ADDRESS",
    "PROPOSED_AUDIT_OPERATIONS",
    "DenyAllSessions",
    "GrpcAuditRecorder",
    "GrpcFlagNotifier",
    "GrpcSessionRoleResolver",
    "NullFlagNotifier",
    "PermissiveFlagTypeValidator",
    "RegistryFlagTypeValidator",
    "UnavailablePersistenceWriteGateway",
]

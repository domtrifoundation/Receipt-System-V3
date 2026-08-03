"""The `BackgroundWorkersServicer` gRPC servicer (`background_workers.proto`) — the
resolution of the design tension `CLAUDE.md`'s own "Known gap" section named: the
deep-dive specifies no wire contract at all, while `docs/PROCESS_TOPOLOGY.md` establishes
every Core API as its own gRPC-reachable process. See `background_workers.proto`'s own
module comment for the full reasoning; in short, this surface is observability/control
only — `ListJobs`/`GetJobHealth`/`GetNextDue` for visibility, `EnableJob` for the one
explicit staff action §10's retry guard requires. Actually running a job stays an
in-process `JobScheduler.dispatch` call, since a registered handler is a live Python
callable inside whichever process holds it, not something a remote caller can invoke by
name.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from .errors import BackgroundWorkersError, code_for
from .registry import JobRegistry

DEFAULT_ADDRESS = "127.0.0.1:50086"
DEFAULT_AUTH_ADDRESS = "127.0.0.1:50056"

#: `EnableJob` is a staff action (§10's own "explicit, never automatic" requirement) —
#: matching `core/task_scheduler/grpc_servicer.py`'s own role-gate posture.
ALLOWED_ROLES = frozenset({"staff", "owner"})

__all__ = ["BackgroundWorkersServicer", "DEFAULT_ADDRESS", "GrpcSessionResolver", "serve"]


class GrpcSessionResolver:
    """Resolves `(user_id, role)` from Auth & Tenancy's real `ValidateSession` RPC,
    synchronously — matching `core/task_scheduler/grpc_servicer.py`'s own equivalent."""

    def __init__(self, address: str = DEFAULT_AUTH_ADDRESS) -> None:
        self._address = address

    def __call__(self, session_id: str) -> tuple[str, str] | None:
        if not session_id:
            return None
        import grpc

        from core.auth.generated import auth_pb2 as pb
        from core.auth.generated import auth_pb2_grpc as pb_grpc

        try:
            with grpc.insecure_channel(self._address) as channel:
                stub = pb_grpc.AuthServiceStub(channel)
                resp = stub.ValidateSession(pb.ValidateSessionRequest(session_id=session_id), timeout=5.0)
        except grpc.RpcError:
            return None
        if resp.error_code or not resp.user_id or not resp.role:
            return None
        return (resp.user_id, resp.role)


def deny_all_sessions(session_id: str) -> tuple[str, str] | None:
    return None


def _registration_to_pb(pb, registration):
    return pb.JobRegistrationInfo(
        job_id=registration.job_id, owning_api=registration.owning_api,
        job_class=registration.job_class.value, idle_only=registration.idle_only,
        event_triggered=registration.event_triggered,
        interval_seconds=registration.interval_seconds or 0,
        scope=registration.scope, description=registration.description,
    )


def _health_to_pb(pb, health):
    return pb.JobHealthInfo(
        job_id=health.job_id, consecutive_failures=health.consecutive_failures,
        total_runs=health.total_runs, total_failures=health.total_failures,
        last_run_at=health.last_run_at.isoformat() if health.last_run_at else "",
        last_outcome=health.last_outcome.value if health.last_outcome else "",
        last_error_detail=health.last_error_detail,
        disabled_at=health.disabled_at.isoformat() if health.disabled_at else "",
        disabled_reason=health.disabled_reason,
    )


class BackgroundWorkersServicer:
    """Implements `BackgroundWorkersService`. Registered by name, so importing the
    generated stubs is `serve()`'s business and this class stays importable without
    them."""

    def __init__(self, registry: JobRegistry | None = None, *, sessions=deny_all_sessions, next_due_source=None) -> None:
        self._registry = registry if registry is not None else JobRegistry()
        self._sessions = sessions
        #: Optional callable returning `tuple[NextDueEstimate, ...]` — ordinarily a bound
        #: `JobScheduler.next_due`, injected rather than constructed here since a real
        #: scheduler needs a `RunStateReader` and pool config this servicer has no basis
        #: to assemble on its own.
        self._next_due_source = next_due_source

    def _resolve(self, session_id: str) -> tuple[str, str]:
        try:
            resolved = self._sessions(session_id)
        except Exception:  # noqa: BLE001 - an unreachable/broken resolver denies, never permits
            resolved = None
        if resolved is None or resolved[1] not in ALLOWED_ROLES:
            raise RoleForbidden("session could not be resolved to an owner/staff role")
        return resolved

    async def ListJobs(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import background_workers_pb2 as pb

        response = pb.ListJobsResponse()
        for registration in self._registry.all_jobs():
            response.jobs.append(_registration_to_pb(pb, registration))
        return response

    async def GetJobHealth(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import background_workers_pb2 as pb

        try:
            health = self._registry.health(request.job_id)
        except BackgroundWorkersError as exc:
            return pb.JobHealthResponse(error_code=code_for(exc), error_detail=str(exc))
        return pb.JobHealthResponse(health=_health_to_pb(pb, health))

    async def EnableJob(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import background_workers_pb2 as pb

        try:
            user_id, _role = self._resolve(request.session_id)
        except RoleForbidden as exc:
            return pb.JobHealthResponse(error_code="ROLE_FORBIDDEN", error_detail=str(exc))

        try:
            health = self._registry.enable(request.job_id, cleared_by=user_id)
        except BackgroundWorkersError as exc:
            return pb.JobHealthResponse(error_code=code_for(exc), error_detail=str(exc))
        return pb.JobHealthResponse(health=_health_to_pb(pb, health))

    async def GetNextDue(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import background_workers_pb2 as pb

        response = pb.NextDueResponse()
        if self._next_due_source is None:
            return response
        for estimate in self._next_due_source():
            response.estimates.append(pb.NextDueEstimateInfo(
                job_id=estimate.job_id, seconds_until_due=estimate.seconds_until_due,
                approximate=estimate.approximate, blocked_by_idle=estimate.blocked_by_idle,
            ))
        return response


class RoleForbidden(Exception):
    """Local to this servicer, mirroring `core/task_scheduler/errors.py::RoleForbidden` —
    this package's own `errors.py` has no role concept (it is not a session-gated API by
    design; only `EnableJob`, added alongside this servicer, needs one)."""


async def serve(address: str = DEFAULT_ADDRESS, *, registry: JobRegistry | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import background_workers_pb2_grpc

    server = grpc.aio.server()
    background_workers_pb2_grpc.add_BackgroundWorkersServiceServicer_to_server(
        BackgroundWorkersServicer(registry), server
    )
    server.add_insecure_port(address)
    await server.start()
    return server

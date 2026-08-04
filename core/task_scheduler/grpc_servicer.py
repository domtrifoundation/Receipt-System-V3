"""The `TaskSchedulerServicer` gRPC adapter over `TaskSchedulerService`
(`task_scheduler.proto`) — the real assembly point `CLAUDE.md`'s own "Known gap" section
named: "§7 specifies a five-RPC gRPC surface ... and there is no `.proto` here yet."
Every behaviour those RPCs translate — allowlist enforcement, cron validation, the
per-tier cap, per-user scoping — was already implemented and tested at the in-process
layer (`store.py`, `registry.py`, `cron.py`); this file and `service.py` are what was
missing.

**`RoleForbidden` is a real addition to `errors.py`, made alongside this file** — this
package's own opening line ("letting an owner/staff user configure their own recurring
actions") implies a role gate `contracts.py`'s own docstring already promised
("`service.py`'s own concern, mirroring `core/audit/service.py`'s injected, fail-closed
`role_resolver`"), but no error code existed for it until this servicer needed one.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from .errors import RoleForbidden, TaskSchedulerError, code_for
from .service import TaskSchedulerService

DEFAULT_ADDRESS = "127.0.0.1:50083"
DEFAULT_AUTH_ADDRESS = "127.0.0.1:50056"

#: Only these roles may schedule tasks at all (this package's own opening line: "letting
#: an owner/staff user configure their own recurring actions") — a `client`-role caller,
#: or an unresolvable session, are both denied identically (`docs/PRINCIPLES.md` §4.2).
ALLOWED_ROLES = frozenset({"staff", "owner"})

__all__ = ["DEFAULT_ADDRESS", "GrpcSessionResolver", "TaskSchedulerServicer", "serve"]


class GrpcSessionResolver:
    """Resolves `(user_id, role)` from Auth & Tenancy's real `ValidateSession` RPC,
    synchronously — matching `core/support_ticketing/service.py::GrpcSessionResolver`'s
    own reasoning for why a sync client, not `grpc.aio`, is the right shape here."""

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
    """The safe default resolver — a process that forgets to wire Auth in gets a closed
    gate, not a silently permissive one (`docs/PRINCIPLES.md` §4.2)."""
    return None


def _task_to_pb(pb, task):
    msg = pb.ScheduledTaskInfo(
        task_id=task.task_id, created_by=task.created_by, action=task.action,
        cron_expression=task.cron_expression, enabled=task.enabled,
        created_at=task.created_at.isoformat(), updated_at=task.updated_at.isoformat(),
    )
    msg.action_params.update({k: str(v) for k, v in task.action_params.items()})
    return msg


def _task_response(pb, result):
    response = pb.TaskResponse(error_code=result.error_code, error_detail=result.error_detail)
    if result.task is not None:
        response.task.CopyFrom(_task_to_pb(pb, result.task))
    return response


class TaskSchedulerServicer:
    """Implements `TaskSchedulerService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        service: TaskSchedulerService | None = None,
        *,
        sessions=deny_all_sessions,
    ) -> None:
        self._service = service if service is not None else TaskSchedulerService()
        self._sessions = sessions

    def _resolve(self, session_id: str) -> tuple[str, str]:
        try:
            resolved = self._sessions(session_id)
        except Exception:  # noqa: BLE001 - an unreachable/broken resolver denies, never permits
            resolved = None
        if resolved is None or resolved[1] not in ALLOWED_ROLES:
            raise RoleForbidden("session could not be resolved to an owner/staff role")
        return resolved

    async def CreateScheduledTask(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import task_scheduler_pb2 as pb

        try:
            user_id, _role = self._resolve(request.session_id)
        except TaskSchedulerError as exc:
            return pb.TaskResponse(error_code=code_for(exc), error_detail=str(exc))

        result = await self._service.create_task(
            user_id, request.action, dict(request.action_params), request.cron_expression,
            enabled=request.enabled,
        )
        return _task_response(pb, result)

    async def UpdateScheduledTask(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import task_scheduler_pb2 as pb

        try:
            user_id, _role = self._resolve(request.session_id)
        except TaskSchedulerError as exc:
            return pb.TaskResponse(error_code=code_for(exc), error_detail=str(exc))

        result = await self._service.update_task(
            user_id, request.task_id,
            action=request.action or None,
            action_params=dict(request.action_params) if request.action_params_set else None,
            cron_expression=request.cron_expression or None,
            enabled=request.enabled if request.enabled_set else None,
        )
        return _task_response(pb, result)

    async def DeleteScheduledTask(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import task_scheduler_pb2 as pb

        try:
            user_id, _role = self._resolve(request.session_id)
        except TaskSchedulerError as exc:
            return pb.DeleteTaskResponse(error_code=code_for(exc), error_detail=str(exc))

        result = await self._service.delete_task(user_id, request.task_id)
        return pb.DeleteTaskResponse(ok=result.ok, error_code=result.error_code, error_detail=result.error_detail)

    async def ListScheduledTasks(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import task_scheduler_pb2 as pb

        try:
            user_id, _role = self._resolve(request.session_id)
        except TaskSchedulerError as exc:
            return pb.ListTasksResponse(error_code=code_for(exc), error_detail=str(exc))

        result = await self._service.list_tasks(user_id)
        response = pb.ListTasksResponse(error_code=result.error_code, error_detail=result.error_detail)
        for task in result.tasks:
            response.tasks.append(_task_to_pb(pb, task))
        return response

    async def ListSchedulableActions(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import task_scheduler_pb2 as pb

        result = self._service.list_schedulable_actions()
        response = pb.ListActionsResponse(error_code=result.error_code, error_detail=result.error_detail)
        for action in result.actions:
            response.actions.append(pb.SchedulableActionInfo(
                name=action.name, description=action.description, param_keys=list(action.param_keys),
            ))
        return response


async def serve(address: str = DEFAULT_ADDRESS, *, service: TaskSchedulerService | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import task_scheduler_pb2_grpc

    server = grpc.aio.server()
    task_scheduler_pb2_grpc.add_TaskSchedulerServiceServicer_to_server(
        TaskSchedulerServicer(service), server
    )
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = await serve(addr)
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        await srv.wait_for_termination()

    asyncio.run(_main())

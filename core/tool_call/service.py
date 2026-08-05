"""The `ToolCallServicer` gRPC servicer (`tool_call.proto`) — the real assembly point
building a real `ToolRegistry` from every tool module in `tools/*.py` and wiring it, plus
`dispatch.dispatch()`, to the wire surface. `CLAUDE.md`'s own "Known gap" section named
this by name: the deep-dive specifies no wire contract at all, and until this session
every module in `tools/*.py` was itself a 0-byte scaffold with nothing to register.

**`GrpcPermissionResolver` is a real, synchronous client against Auth's
`ValidateSession`** — `registry.PermissionResolver`'s own type is `Callable[[ToolContext],
Role | None]`, not a coroutine function, matching every other synchronous resolver this
session built (`core/task_scheduler/grpc_servicer.py`, `core/support_ticketing/
service.py`).

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

import asyncio
import json

from common.frozen_dict import FrozenDict

from .contracts import CALLING_API_ALLOWED_CATEGORIES, ToolContext
from .dispatch import InMemoryAuditRecorder, dispatch
from .registry import PermissionResolver, ToolRegistry, deny_all_permissions
from .tools.geo_tools import register_geo_tools
from .tools.persistence_write_tools import register_persistence_write_tools
from .tools.query_tools import register_query_tools
from .tools.settings_tools import register_settings_tools
from .tools.vendor_tools import register_vendor_tools

DEFAULT_ADDRESS = "127.0.0.1:50087"
DEFAULT_AUTH_ADDRESS = "127.0.0.1:50056"

__all__ = [
    "DEFAULT_ADDRESS",
    "GrpcPermissionResolver",
    "ToolCallServicer",
    "build_default_registry",
    "serve",
]


def build_default_registry() -> ToolRegistry:
    """The real assembly point — every tool module registers itself here. `service.py`'s
    own constructor calls this by default so a servicer built with no arguments actually
    has real tools in it, not an empty registry nobody populated."""
    registry = ToolRegistry()
    register_geo_tools(registry)
    register_vendor_tools(registry)
    register_query_tools(registry)
    register_persistence_write_tools(registry)
    register_settings_tools(registry)
    return registry


class GrpcPermissionResolver:
    """Resolves a `Role` from Auth & Tenancy's real `ValidateSession` RPC, synchronously —
    `registry.PermissionResolver`'s own type is a plain callable, not a coroutine
    function."""

    def __init__(self, address: str = DEFAULT_AUTH_ADDRESS) -> None:
        self._address = address

    def __call__(self, context: ToolContext):
        if not context.session_id:
            return None
        import grpc

        from core.auth.contracts import Role
        from core.auth.generated import auth_pb2 as pb
        from core.auth.generated import auth_pb2_grpc as pb_grpc

        try:
            with grpc.insecure_channel(self._address) as channel:
                stub = pb_grpc.AuthServiceStub(channel)
                resp = stub.ValidateSession(pb.ValidateSessionRequest(session_id=context.session_id), timeout=5.0)
        except grpc.RpcError:
            return None
        if resp.error_code or not resp.role:
            return None
        try:
            return Role(resp.role)
        except ValueError:
            return None


def _context_from_pb(pb_context) -> ToolContext:
    return ToolContext(
        run_id=pb_context.run_id, user_id=pb_context.user_id,
        calling_api=pb_context.calling_api, session_id=pb_context.session_id,
    )


class ToolCallServicer:
    """Implements `ToolCallService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        resolver: PermissionResolver = deny_all_permissions,
        audit=None,
        metrics=None,
    ) -> None:
        self._registry = registry if registry is not None else build_default_registry()
        self._resolver = resolver
        self._audit = audit or InMemoryAuditRecorder()
        self._metrics = metrics

    async def ListTools(self, request, context=None):  # noqa: N802 - gRPC naming
        """The manifest Inference API's own tool-calling orchestrator builds its
        constrained-decoding grammar from (deep-dive §5) — filtered to exactly what this
        `calling_api` is enabled for AND the resolved caller's role covers, the same two
        independent gates `registry.ToolRegistry.check()` enforces at dispatch time."""
        from .generated import tool_call_pb2 as pb

        tool_context = _context_from_pb(request.context)
        allowed_categories = CALLING_API_ALLOWED_CATEGORIES.get(tool_context.calling_api, frozenset())
        role = self._resolver(tool_context)

        from .contracts import CATEGORY_ALLOWED_ROLES

        response = pb.ListToolsResponse()
        for spec in self._registry.all_specs():
            if spec.category not in allowed_categories:
                continue
            if role is None or role not in CATEGORY_ALLOWED_ROLES.get(spec.category, frozenset()):
                continue
            response.tools.append(pb.ToolSpecInfo(
                name=spec.name, description=spec.description,
                parameters_schema_json=json.dumps(dict(spec.parameters_schema)),
                category=spec.category.value,
            ))
        return response

    async def DispatchTool(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import tool_call_pb2 as pb

        tool_context = _context_from_pb(request.context)
        try:
            arguments = json.loads(request.arguments_json) if request.arguments_json else {}
        except json.JSONDecodeError as exc:
            return pb.DispatchToolResponse(
                tool_name=request.tool_name, error=str(exc), error_code="INVALID_ARGUMENTS",
            )

        result = await asyncio.to_thread(
            dispatch, self._registry, tool_context, request.tool_name, arguments,
            resolver=self._resolver, audit=self._audit, metrics=self._metrics,
        )
        return pb.DispatchToolResponse(
            tool_name=result.tool_name, result_json=json.dumps(dict(result.result)),
            error=result.error or "", error_code=result.error_code,
        )


async def serve(address: str = DEFAULT_ADDRESS, *, registry: ToolRegistry | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import tool_call_pb2_grpc

    server = grpc.aio.server()
    tool_call_pb2_grpc.add_ToolCallServiceServicer_to_server(ToolCallServicer(registry), server)
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
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('tool_call')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())

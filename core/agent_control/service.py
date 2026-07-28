"""The `AgentControlService` gRPC servicer (`v3-deepdive-55-agent-control-api.md` §9).

This is the single enforcement point. Both surfaces — the MCP server and the headless CLI —
are gRPC *clients* of this service, not independent implementations, which is what makes
"an agent is never more capable than the human who authorized it" a structural property
rather than something each surface has to remember to check.

Order of enforcement on every action, deliberately: authenticate → resolve tool → scope
check → rate limit → execute → audit. The audit write happens for every attempt, including
refusals (§6, "no exceptions") — a rejected action is often the more interesting record.
"""

from __future__ import annotations

import json
from concurrent import futures

import grpc

from common.frozen_dict import FrozenDict

from .backends.base import CoreBackend
from .backends.local import LocalCoreBackend
from .contracts import AgentAction, AgentToken, ToolResult, utcnow
from .errors import (
    AgentControlError,
    CoreUnavailable,
    OwnerRoleForbidden,
    RateLimited,
    ScopeDenied,
    TokenAuthError,
    UnknownTool,
)
from .generated import agent_control_pb2 as pb
from .generated import agent_control_pb2_grpc as pb_grpc
from .mcp.tool_definitions import TOOLS_BY_NAME, enabled_tools
from .rate_limit import RateLimiter
from .store import AgentStore
from .token_lifecycle import TokenLifecycle

DEFAULT_ADDRESS = "127.0.0.1:50055"


def _iso(dt) -> str:
    return dt.isoformat() if dt else ""


def _token_info(t: AgentToken) -> pb.AgentTokenInfo:
    return pb.AgentTokenInfo(
        token_id=t.token_id, issued_by=t.issued_by, issued_to_label=t.issued_to_label,
        scopes=list(t.scopes), role=t.role, issued_at=_iso(t.issued_at),
        expires_at=_iso(t.expires_at), revoked_at=_iso(t.revoked_at), active=t.is_active(),
    )


class AgentControlServicer(pb_grpc.AgentControlServiceServicer):
    def __init__(self, store: AgentStore, backend: CoreBackend | None = None) -> None:
        self._store = store
        self._tokens = TokenLifecycle(store)
        self._limiter = RateLimiter(store)
        self._backend: CoreBackend = backend or LocalCoreBackend()

    # ------------------------------------------------------------- tokens
    def IssueAgentToken(self, request, context):
        try:
            expires_in = None
            if request.expires_in_seconds:
                from datetime import timedelta
                expires_in = timedelta(seconds=request.expires_in_seconds)
            issued = self._tokens.issue_token(
                issued_by=request.issued_by,
                issued_to_label=request.issued_to_label,
                scopes=tuple(request.scopes) or ("read_only", "dev_observability"),
                role=request.role or "staff",
                expires_in=expires_in,
            )
            return pb.AgentTokenResponse(
                token=_token_info(issued.token), plaintext_token=issued.plaintext
            )
        except OwnerRoleForbidden as e:
            return pb.AgentTokenResponse(error_code="OWNER_ROLE_FORBIDDEN", error_detail=str(e))
        except ValueError as e:
            return pb.AgentTokenResponse(error_code="INVALID_REQUEST", error_detail=str(e))

    def RevokeAgentToken(self, request, context):
        now = utcnow()
        ok = self._tokens.revoke(request.token_id)
        if not ok:
            return pb.RevokeResponse(
                revoked=False, error_code="NOT_REVOCABLE",
                error_detail="no such token, or it was already revoked",
            )
        return pb.RevokeResponse(revoked=True, revoked_at=_iso(now))

    def ListAgentTokens(self, request, context):
        tokens = self._tokens.list_tokens(include_inactive=request.include_inactive)
        return pb.ListTokensResponse(tokens=[_token_info(t) for t in tokens])

    # ------------------------------------------------------------- actions
    def ExecuteAgentAction(self, request, context):
        # 1. Authenticate. Raises by design — the one carve-out from errors-as-data.
        try:
            token = self._tokens.authenticate(request.token)
        except TokenAuthError as e:
            return pb.AgentActionResponse(
                ok=False, error_code=type(e).__name__, error_detail=str(e)
            )

        # 2. Resolve the tool.
        tool = TOOLS_BY_NAME.get(request.tool_name)
        if tool is None:
            self._audit(token.token_id, request.tool_name, None, {}, "unknown_tool")
            return pb.AgentActionResponse(
                ok=False, error_code="UNKNOWN_TOOL",
                error_detail=f"{request.tool_name!r} is not an exposed tool",
            )

        try:
            args = json.loads(request.arguments_json) if request.arguments_json else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            self._audit(token.token_id, tool.name, tool.category, {}, "bad_arguments", str(e))
            return pb.AgentActionResponse(
                ok=False, error_code="BAD_ARGUMENTS", error_detail=str(e),
                tool_category=tool.category.value,
            )

        # 3. Scope check.
        if tool not in enabled_tools(token.scopes):
            self._audit(token.token_id, tool.name, tool.category, args, "scope_denied")
            return pb.AgentActionResponse(
                ok=False, error_code="SCOPE_DENIED",
                error_detail=f"token scopes {list(token.scopes)} do not cover "
                             f"category {tool.category.value!r}",
                tool_category=tool.category.value,
            )

        # 4. Rate limit.
        try:
            self._limiter.check(token.token_id, tool.category)
        except RateLimited as e:
            self._audit(token.token_id, tool.name, tool.category, args, "rate_limited", str(e))
            return pb.AgentActionResponse(
                ok=False, error_code="RATE_LIMITED", error_detail=str(e),
                tool_category=tool.category.value,
            )

        # 5. Execute.
        result = self._invoke(tool, args)

        # 6. Audit — always, success or failure.
        self._audit(
            token.token_id, tool.name, tool.category, args,
            "ok" if result.ok else "error", result.error,
        )
        return pb.AgentActionResponse(
            ok=result.ok,
            payload_json=json.dumps(dict(result.payload), default=str),
            error_code="" if result.ok else "TOOL_ERROR",
            error_detail=result.error,
            tool_category=tool.category.value,
        )

    def _invoke(self, tool, args: dict) -> ToolResult:
        handler = getattr(self._backend, tool.handler, None)
        if handler is None:
            return ToolResult.failure(f"backend {self._backend.name()!r} has no {tool.handler!r}")
        try:
            return ToolResult.success(**handler(**args))
        except CoreUnavailable as e:
            return ToolResult.failure(f"core unavailable: {e}")
        except TypeError as e:
            return ToolResult.failure(f"invalid arguments for {tool.name}: {e}")
        except AgentControlError as e:
            return ToolResult.failure(str(e))

    def _audit(self, token_id, tool_name, category, args, outcome, detail="") -> None:
        from .contracts import ToolCategory
        self._store.append_audit(AgentAction(
            token_id=token_id, tool_name=tool_name,
            category=category or ToolCategory.READ_ONLY,
            arguments=FrozenDict(args), at=utcnow(), outcome=outcome, detail=detail,
        ))


def serve(
    address: str = DEFAULT_ADDRESS,
    store: AgentStore | None = None,
    backend: CoreBackend | None = None,
) -> grpc.Server:
    """Start the service. Returns the running server so a caller can stop it.

    Pass a `:0` port to bind an ephemeral one — the actually-bound address is attached to
    the returned server as `bound_address`. Worth having rather than hard-coding a port:
    Windows reserves scattered ranges in the 50000s (`netsh interface ipv4 show
    excludedportrange tcp`), so a fixed high port is not reliably bindable across machines.
    """
    store = store or AgentStore()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_AgentControlServiceServicer_to_server(
        AgentControlServicer(store, backend), server
    )
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import sys

    addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
    srv = serve(addr)
    print(f"AgentControlService listening on {addr}", file=sys.stderr)
    srv.wait_for_termination()

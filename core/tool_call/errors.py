"""Tool Call API error taxonomy.

These are surfaced as `ToolResult.error_code`/`error`, never raised across the gRPC boundary
(`docs/PRINCIPLES.md` §4.1). A tool handler is free to raise internally — it is a thin wrapper
around another API and the easiest thing for it to do on a real failure — and `dispatch.py` is
the one place every such exception is caught and converted; nothing in this package lets a
handler's exception propagate past `dispatch.dispatch()`.

Fail-closed is structural here, not a convention a caller has to remember (`docs/PRINCIPLES.md`
§4.2): `UnregisteredTool`, `PermissionDenied` and `ContextNotEnabled` are the three ways a
request is refused before a handler ever runs, and all three produce the identical shape of
result a caller cannot mistake for success.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class ToolCallError(Exception):
    """Base for everything this package raises internally. Never crosses the boundary."""


class UnregisteredTool(ToolCallError):
    """No tool with this name is registered. Fails closed: an unknown name is refused, never
    treated as a no-op success or dispatched to a best-guess handler."""


class ContextNotEnabled(ToolCallError):
    """`ToolContext.calling_api` is unrecognised, or recognised but not permitted to draw
    tools of this category at all (`contracts.CALLING_API_ALLOWED_CATEGORIES`).

    Distinct from `PermissionDenied`: this is "this calling surface never gets this category,
    regardless of who is behind it," resolved from static per-context configuration, not from
    the caller's own resolved role.
    """


class PermissionDenied(ToolCallError):
    """The caller's resolved role does not cover this tool's category, or the role could not
    be resolved at all.

    An unresolvable role is denied on the same footing as an insufficient one — there is no
    third outcome. A `PermissionResolver` that raises, times out, or returns `None` all reach
    this exact branch (`docs/PRINCIPLES.md` §4.2: an unresolvable permission check means
    denied, never a default-allow).
    """


class ToolUnavailable(ToolCallError):
    """The tool is registered and permitted, but its own live-availability check reports the
    underlying capability is not reachable right now (deep-dive §3.4's "don't offer an
    always-failing tool" pattern, re-checked at dispatch time rather than trusted from
    whatever manifest the caller built earlier)."""


class InvalidArguments(ToolCallError):
    """The supplied arguments are not a mapping, or fail a tool's own argument validation
    before its handler is invoked."""


class ToolTimedOut(ToolCallError):
    """A handler did not return within its allotted time.

    The underlying call may still be running in the background — a synchronous handler
    cannot be safely killed mid-call, only abandoned — so this reports "no answer in time,"
    not "the operation did not happen." See `dispatch.py`'s own docstring for why this is an
    honest limitation rather than a bug.
    """


class ToolRaised(ToolCallError):
    """A handler raised an exception this package did not otherwise recognise.

    The catch-all conversion at the dispatch boundary: whatever a thin wrapper's own callee
    (Architect, Persistence, a future Geo/Address or Search/Query client) raised becomes data
    here rather than propagating, exactly as `docs/PRINCIPLES.md` §4.1 requires.
    """


#: Stable wire codes (`docs/templates/new_grpc_endpoint.md`'s field-only-append discipline
#: applies to these the same way it applies to a `.proto` field number: added, never renamed
#: or reused, because a caller may be branching on one).
ERROR_CODES: FrozenDict = FrozenDict(
    {
        UnregisteredTool: "UNREGISTERED_TOOL",
        ContextNotEnabled: "CONTEXT_NOT_ENABLED",
        PermissionDenied: "PERMISSION_DENIED",
        ToolUnavailable: "TOOL_UNAVAILABLE",
        InvalidArguments: "INVALID_ARGUMENTS",
        ToolTimedOut: "TOOL_TIMED_OUT",
        ToolRaised: "TOOL_RAISED",
    }
)

#: Operator-facing one-liners, kept next to the codes so a client that only has the code
#: still has something to show (`FrozenDict` per §2.1.1).
ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "UNREGISTERED_TOOL": "no tool with that name is registered",
        "CONTEXT_NOT_ENABLED": "this calling context is not enabled for that tool's category",
        "PERMISSION_DENIED": "the caller's resolved role does not permit that tool",
        "TOOL_UNAVAILABLE": "the tool's underlying capability is not reachable right now",
        "INVALID_ARGUMENTS": "the supplied arguments are not valid for that tool",
        "TOOL_TIMED_OUT": "the tool did not return a result within its allotted time",
        "TOOL_RAISED": "the tool's own handler raised an unhandled exception",
        "INTERNAL": "an unexpected internal error occurred",
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped.

    Unmapped is deliberately not an exception of its own: a caller receiving `INTERNAL` with a
    real detail string is strictly better off than one receiving a crash from the error path
    itself (matching `core/logs/errors.py`'s own `code_for`).
    """
    return ERROR_CODES.get(type(exc), "INTERNAL")


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "ContextNotEnabled",
    "InvalidArguments",
    "PermissionDenied",
    "ToolCallError",
    "ToolRaised",
    "ToolTimedOut",
    "ToolUnavailable",
    "UnregisteredTool",
    "code_for",
]

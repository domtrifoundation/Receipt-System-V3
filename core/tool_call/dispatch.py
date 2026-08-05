"""Runs one requested tool call. Never raises across the boundary (`docs/PRINCIPLES.md` §4.1).

`dispatch()` is the only place a `RegisteredTool.handler`'s own exception is caught — a tool
is a thin wrapper around another API's call (deep-dive §1) and the natural way for that call
to fail is to raise, exactly like V2's own tools did. Converting that into `ToolResult` data
here, once, is what lets every handler in `tools/*.py` stay a plain function that raises on
trouble rather than every one of them separately remembering to catch and wrap its own
failures.

**Concurrency**: this package has no compute of its own — every tool wraps a call into
another API (deep-dive §6, the same conclusion `core/agent_control/service.py` reaches for
its own dispatch). `ToolTimedOut` enforcement uses a thread-pool future rather than `asyncio`
specifically because a registered handler is a plain synchronous callable (matching
`RegisteredTool.handler`'s own signature and `core/agent_control/service.py`'s `_invoke`) —
and because a synchronous call cannot be safely cancelled mid-flight, a timeout here means "no
answer arrived in time," never "the underlying call stopped." That is an honest limitation,
not a bug: see `errors.ToolTimedOut`'s own docstring.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from concurrent import futures
from typing import Protocol, runtime_checkable

from common.frozen_dict import FrozenDict

from .contracts import ToolAuditRecord, ToolCategory, ToolContext, ToolResult
from .errors import (
    ContextNotEnabled,
    ERROR_CODES,
    InvalidArguments,
    PermissionDenied,
    ToolCallError,
    ToolRaised,
    ToolTimedOut,
    ToolUnavailable,
    UnregisteredTool,
    code_for,
)
from .metrics import ToolCallMetricsCollector
from .registry import PermissionResolver, RegisteredTool, ToolRegistry, deny_all_permissions

#: Reasoned, not yet bench-measured (`docs/PRINCIPLES.md` §5's standing discipline: a default
#: like this is provisional until the bench suite confirms it). 30s is generous enough for a
#: thin wrapper's own network round trip to another Core API without leaving the agentic loop
#: (`v3-deepdive-07-tool-call-api.md` §3.3, `max_rounds` default 8) waiting so long that a
#: single stuck tool call dominates the whole round budget.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: The categories `docs/PRINCIPLES.md` §4.2/task-level "every privileged invocation is
#: audited" reaches. `READ_ONLY` and `DEV_OBSERVABILITY` are pure reads with no security or
#: compliance weight of their own (`core/audit/CLAUDE.md`'s own boundary: Audit answers "who
#: did something with real security/compliance weight," and a lookup is not that). Both
#: mutating categories are, by construction (deep-dive §4): `MUTATING_STAGED` writes into an
#: existing review/audit gate and `TEST_EXECUTION` has real, disruptive side effects.
PRIVILEGED_CATEGORIES: frozenset[ToolCategory] = frozenset(
    {ToolCategory.MUTATING_STAGED, ToolCategory.TEST_EXECUTION}
)

_DEFAULT_EXECUTOR = futures.ThreadPoolExecutor(
    max_workers=16, thread_name_prefix="tool-call-dispatch"
)


@runtime_checkable
class AuditRecorder(Protocol):
    """Where a `ToolAuditRecord` goes. See that contract's own docstring for why this is not
    `core.audit.contracts.AuditEvent` directly."""

    def record(self, entry: ToolAuditRecord) -> None: ...


class InMemoryAuditRecorder:
    """The safe default: genuinely records every privileged attempt, in-process.

    Not a no-op, deliberately: an audit *obligation* defaulting to silently dropping every
    record would be the wrong direction to fail in (`docs/PRINCIPLES.md` §4.3 — never
    silently override/omit a thing that is supposed to happen). This is the bridge until
    whichever process assembles a running `ToolCallServicer` wires in a real cross-process
    client to Audit API's `RecordAction` RPC — the identical shape `core/audit/service.py`'s
    own injected, safely-defaulted `role_resolver` already uses for its own cross-API
    dependency on Auth, and the same bounded-exception precedent `core/agent_control/store.py`
    documents for keeping its own audit trail in-process ahead of a real integration.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[ToolAuditRecord] = []

    def record(self, entry: ToolAuditRecord) -> None:
        with self._lock:
            self._entries.append(entry)

    def entries(self) -> tuple[ToolAuditRecord, ...]:
        with self._lock:
            return tuple(self._entries)


def _safe_frozen(arguments: object) -> FrozenDict:
    if isinstance(arguments, Mapping):
        return FrozenDict(dict(arguments))
    return FrozenDict({})


def _denied(tool_name: str, exc: ToolCallError) -> ToolResult:
    return ToolResult(tool_name=tool_name, error=str(exc), error_code=code_for(exc))


def _maybe_audit(
    audit: AuditRecorder,
    metrics: ToolCallMetricsCollector | None,
    context: ToolContext,
    entry: RegisteredTool | None,
    arguments: object,
    outcome: str,
    detail: str,
) -> None:
    """Audit every privileged attempt — success, denial, timeout, or raise alike.

    An attempted mutating action is real evidence regardless of how it ended (matching
    `core/agent_control/service.py`'s own "a rejected action is often the more interesting
    record"). Nothing here is gated on `entry` having passed permission — a `PermissionDenied`
    or `ToolUnavailable` refusal of a `MUTATING_STAGED`/`TEST_EXECUTION` tool is audited too,
    which is only possible because `entry` is looked up once via `ToolRegistry.get()` before
    the enforcement gate runs, independent of whether that gate ends up allowing the call.
    """
    if entry is None or entry.spec.category not in PRIVILEGED_CATEGORIES:
        return
    record = ToolAuditRecord(
        run_id=context.run_id,
        user_id=context.user_id,
        calling_api=context.calling_api,
        tool_name=entry.spec.name,
        category=entry.spec.category,
        arguments=_safe_frozen(arguments),
        outcome=outcome,
        detail=detail,
    )
    try:
        audit.record(record)
    except Exception:  # noqa: BLE001 - an audit-sink failure must not corrupt or block the
        # tool result already computed; it is a second, independent problem (`docs/
        # PRINCIPLES.md` §4.4). It is not silently invisible either: `metrics` only increments
        # on a *successful* write, so a gap between `invocations_total` (privileged ones) and
        # `audit_records_written` is the operator-visible signal something degraded here.
        return
    if metrics is not None:
        metrics.increment("audit_records_written")


def dispatch(
    registry: ToolRegistry,
    context: ToolContext,
    tool_name: str,
    arguments: object,
    *,
    resolver: PermissionResolver = deny_all_permissions,
    audit: AuditRecorder | None = None,
    metrics: ToolCallMetricsCollector | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    executor: futures.Executor | None = None,
) -> ToolResult:
    """Run one tool call end to end: enforce, invoke, convert, audit. Never raises.

    `arguments` is deliberately typed `object`, not `Mapping`, because "the caller did not
    send a mapping at all" is itself one of the failures this boundary must convert to data
    rather than let raise as a `TypeError` from an `isinstance` check a caller forgot to guard.
    """
    audit = audit or InMemoryAuditRecorder()
    executor = executor or _DEFAULT_EXECUTOR
    if metrics is not None:
        metrics.increment("invocations_total")

    # Looked up once, ahead of enforcement, purely so `_maybe_audit` can record a privileged
    # tool's category even when the call that follows is about to be denied. This is a read
    # of the registry's own public surface, not a bypass of `check()` below.
    entry_peek = registry.get(tool_name)

    try:
        entry = registry.check(tool_name, context, resolver)
    except UnregisteredTool as exc:
        if metrics is not None:
            metrics.increment("denied_unregistered")
        # Never audited: with no registered entry there is no category to know is privileged.
        return _denied(tool_name, exc)
    except ContextNotEnabled as exc:
        if metrics is not None:
            metrics.increment("denied_context")
        _maybe_audit(audit, metrics, context, entry_peek, arguments, "context_not_enabled", str(exc))
        return _denied(tool_name, exc)
    except PermissionDenied as exc:
        if metrics is not None:
            metrics.increment("denied_permission")
        _maybe_audit(audit, metrics, context, entry_peek, arguments, "permission_denied", str(exc))
        return _denied(tool_name, exc)
    except ToolUnavailable as exc:
        if metrics is not None:
            metrics.increment("denied_unavailable")
        _maybe_audit(audit, metrics, context, entry_peek, arguments, "unavailable", str(exc))
        return _denied(tool_name, exc)

    if not isinstance(arguments, Mapping):
        exc = InvalidArguments(f"arguments for {tool_name!r} must be a mapping")
        if metrics is not None:
            metrics.increment("denied_invalid_arguments")
        _maybe_audit(audit, metrics, context, entry, arguments, "invalid_arguments", str(exc))
        return _denied(tool_name, exc)

    # The frozen copy is what the handler receives — a caller's own live dict, mutated after
    # this call returns, must never be able to change what the handler already saw or what
    # the audit record above already captured (`docs/PRINCIPLES.md` §2.1).
    frozen_args = FrozenDict(dict(arguments))

    outcome: str
    detail: str
    try:
        raw = executor.submit(entry.handler, frozen_args, context).result(timeout=timeout)
    except futures.TimeoutError:
        if metrics is not None:
            metrics.increment("timed_out")
        outcome, detail = "timed_out", f"{tool_name!r} exceeded its {timeout}s allotment"
        result = ToolResult(tool_name=tool_name, error=detail, error_code=ERROR_CODES[ToolTimedOut])
    except Exception as exc:  # noqa: BLE001 - the one place a handler's own exception is
        # caught and converted to data, per `docs/PRINCIPLES.md` §4.1.
        if metrics is not None:
            metrics.increment("handler_raised")
        outcome, detail = "raised", str(exc)
        result = ToolResult(tool_name=tool_name, error=detail, error_code=ERROR_CODES[ToolRaised])
    else:
        if not isinstance(raw, Mapping):
            if metrics is not None:
                metrics.increment("handler_raised")
            outcome = "raised"
            detail = f"handler for {tool_name!r} returned a non-mapping payload"
            result = ToolResult(tool_name=tool_name, error=detail, error_code=ERROR_CODES[ToolRaised])
        else:
            if metrics is not None:
                metrics.increment("invocations_ok")
            outcome, detail = "ok", ""
            result = ToolResult(tool_name=tool_name, result=FrozenDict(dict(raw)))

    _maybe_audit(audit, metrics, context, entry, frozen_args, outcome, detail)
    return result


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "PRIVILEGED_CATEGORIES",
    "AuditRecorder",
    "InMemoryAuditRecorder",
    "dispatch",
]

"""The tool Provider Registry (`docs/PRINCIPLES.md` §1.2) — which tools exist, and the single
place that answers "is this specific call, from this specific context, allowed right now."

This is a genuine Provider Registry in this project's own sense: any number of tools register
here, several calling contexts draw from the same registry at once (the reconciliation loop
and Agent Control's own MCP server are not two registries, they are two `calling_api` values
filtering one), and the registry — not each tool, not each caller — is what decides which
subset is even visible to a given context (deep-dive §3.4's carried-forward V2 pattern:
"don't offer a tool that can only fail" is one half of that decision; §4's per-context
category gate is the other).

**`check()` is the single enforcement path, used by both `enabled_tools()` (building a
manifest for Inference API to see) and `dispatch.dispatch()` (actually running a call).**
Building the manifest from one filter and enforcing from a second, subtly different one is
exactly how a tool ends up dispatchable that a client was never supposed to see in its own
manifest — so there is one method, not two independently-maintained opinions.

**Fail-closed is structural, not a per-call convention** (`docs/PRINCIPLES.md` §4.2): a
`PermissionResolver` that raises, hangs, or returns `None` all reach the identical
`PermissionDenied` branch, and a `RegisteredTool.available` check that raises is treated as
"unavailable," never as "the check didn't run, so allow it."
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from common.frozen_dict import FrozenDict
from core.auth.contracts import Role

from .contracts import CALLING_API_ALLOWED_CATEGORIES, CATEGORY_ALLOWED_ROLES, ToolContext, ToolSpec
from .errors import ContextNotEnabled, PermissionDenied, ToolUnavailable, UnregisteredTool

#: Resolves the caller's role *from their session, via Auth & Tenancy*, never from a field the
#: caller supplies about themselves (this task's own non-negotiable rule, and the concrete
#: instance of `docs/PRINCIPLES.md` §4.2 this package is built around). Returning `None` is
#: the "cannot resolve" signal — an expired/invalid/absent session, or Auth itself being
#: unreachable — and it is handled identically to an insufficient role: denied.
#:
#: Matches `core/audit/service.py`'s own `RoleResolver` idiom deliberately: a `Callable` typed
#: against the caller's own context type, injected with a safe default, exactly as that
#: module's own docstring describes the pattern for exactly this kind of cross-API check.
PermissionResolver = Callable[[ToolContext], Role | None]


def deny_all_permissions(context: ToolContext) -> None:
    """The safe default resolver. Denies every role, unconditionally.

    Auth & Tenancy resolution is a live cross-process call (`AuthService.ValidateSession`,
    `core/auth/service.py`) that whatever process assembles this service's `serve()` wires in
    for real — this default exists so a caller that forgets to wire one in gets a closed
    permission gate, not a silently-permissive one (`docs/PRINCIPLES.md` §4.2, matching
    `core/audit/service.py`'s own `deny_all_roles`).
    """
    return None


def _safe_resolve(resolver: PermissionResolver, context: ToolContext):
    """Never let a resolver's own failure become an allow.

    A resolver that raises (Auth unreachable, a malformed session lookup) or simply takes too
    long is exactly the "unresolvable permission" case `docs/PRINCIPLES.md` §4.2 requires to
    fail closed — caught here once so every caller of `check()` gets that guarantee for free
    rather than having to remember to wrap their own resolver call.
    """
    try:
        return resolver(context)
    except Exception:  # noqa: BLE001 - any resolver failure means "cannot resolve" = denied
        return None


@dataclass(frozen=True)
class RegisteredTool:
    """A `ToolSpec` paired with the logic `contracts.py` deliberately does not hold: the
    handler that actually runs it, and an optional live-availability check.

    `handler` takes `(arguments: FrozenDict, context: ToolContext)` and returns a plain
    `Mapping` payload, or raises — `dispatch.py` is the only place a handler's exception is
    caught and converted to `ToolResult` data (`docs/PRINCIPLES.md` §4.1).

    `available` is deep-dive §3.4's "don't offer an always-failing tool" pattern, generalised
    beyond geocoding: a tool wrapping a capability that is not configured or not reachable
    right now reports itself unavailable rather than being offered only to fail on every call.
    `None` means "always available" (the ordinary case for a pure-logic tool).
    """

    spec: ToolSpec
    handler: Callable[[FrozenDict, ToolContext], Mapping[str, Any]]
    available: Callable[[], bool] | None = None

    def is_available(self) -> bool:
        if self.available is None:
            return True
        try:
            return bool(self.available())
        except Exception:  # noqa: BLE001 - an availability check that raises means unavailable,
            # never "the check didn't run, so allow it" (`docs/PRINCIPLES.md` §4.4).
            return False


class ToolRegistry:
    """The registry itself. A genuinely mutable internal registry populated at startup — a
    plain `dict`, not a `FrozenDict`, and the distinction is intentional and visible in the
    type (`docs/PRINCIPLES.md` §2.1.1: that rule reaches module-level *constants*, not this).
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        spec: ToolSpec,
        handler: Callable[[FrozenDict, ToolContext], Mapping[str, Any]],
        *,
        available: Callable[[], bool] | None = None,
    ) -> None:
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler, available=available)

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def all_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(entry.spec for entry in self._tools.values())

    # ------------------------------------------------------------- the one enforcement path

    def check(
        self, name: str, context: ToolContext, resolver: PermissionResolver = deny_all_permissions
    ) -> RegisteredTool:
        """Return the `RegisteredTool` for `name` if `context` may call it right now, else
        raise one of `errors.py`'s taxonomy. Order is deliberate — cheapest and most
        information-revealing-safe checks first:

        1. registered at all (`UnregisteredTool`)
        2. this calling context is enabled for this category at all (`ContextNotEnabled`)
        3. the resolved caller's role covers this category (`PermissionDenied`)
        4. the tool's own capability is actually reachable right now (`ToolUnavailable`)
        """
        entry = self._tools.get(name)
        if entry is None:
            raise UnregisteredTool(name)

        allowed_categories = CALLING_API_ALLOWED_CATEGORIES.get(context.calling_api, frozenset())
        if entry.spec.category not in allowed_categories:
            raise ContextNotEnabled(
                f"{context.calling_api!r} is not enabled for category "
                f"{entry.spec.category.value!r}"
            )

        role = _safe_resolve(resolver, context)
        allowed_roles = CATEGORY_ALLOWED_ROLES.get(entry.spec.category, frozenset())
        if role is None or role not in allowed_roles:
            raise PermissionDenied(
                f"caller's resolved role does not permit category {entry.spec.category.value!r}"
            )

        if not entry.is_available():
            raise ToolUnavailable(f"{name!r} is registered but not reachable right now")

        return entry

    def enabled_tools(
        self, context: ToolContext, resolver: PermissionResolver = deny_all_permissions
    ) -> tuple[ToolSpec, ...]:
        """The manifest Inference API's tool-calling orchestrator builds its constrained-
        decoding grammar from (deep-dive §3.4, §5) — every tool `context` may actually call
        right now, filtered through the identical gate `dispatch()` re-checks at call time.
        """
        visible: list[ToolSpec] = []
        for name in self._tools:
            try:
                self.check(name, context, resolver)
            except (UnregisteredTool, ContextNotEnabled, PermissionDenied, ToolUnavailable):
                continue
            visible.append(self._tools[name].spec)
        return tuple(sorted(visible, key=lambda s: s.name))


__all__ = [
    "PermissionResolver",
    "RegisteredTool",
    "ToolRegistry",
    "deny_all_permissions",
]

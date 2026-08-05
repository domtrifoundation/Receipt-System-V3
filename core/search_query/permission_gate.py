"""The cross-user and cross-group authorization gate
(`v3-deepdive-21-search-query-api.md` §4, §7's "break-glass expiry mid-session test").

**A third, structurally distinct access shape sits alongside break-glass here, and the
deep-dive is explicit they are never merged into one check** (§4): a staff/owner cross-user
read is gated through Auth's own break-glass ledger; an ordinary client reading across users
is gated through Groups' own `is_group_manager` standing instead, a persistent, non-expiring
relationship, never modeled as "break-glass that never expires"
(`core/groups/CLAUDE.md`'s own framing). `authorize_search` below keeps both paths visibly
distinct rather than one function silently branching between them.

**Every check here is re-evaluated at query time, never once at session start** (§4). A
break-glass grant expiring mid-session must correctly fail the very next query without the
session itself needing to be revoked — this module holds no cache of a prior answer, the
identical discipline `core/groups/permission_gate.py`'s own `is_group_manager` documents for
its own "live re-check" testing hook, applied here to a second, independent access shape.

**Trust model, stated precisely because it differs from `core/groups/permission_gate.py`'s
own.** Groups resolves the caller from a live session through Auth and treats an unresolvable
session as denial — the correct posture for the system-administration actions Groups itself
gates. Search/Query instead trusts `requesting_user_id`/`requesting_role` as given, the
identical model `core/logs/query.py`'s own `LogQuery.requesting_user_id` already uses for this
exact class of read: whatever resolved the caller's session upstream (Gateway, or an
in-process caller that already holds a validated `Session`) is expected to have attached the
correct values, and this module holds no session concept of its own. This is a deliberate
choice, not an oversight — see this package's own `CLAUDE.md` for the reasoning recorded
alongside it.

**Fails closed** (`docs/PRINCIPLES.md` §4.2): no checker wired up, or one that raises, is
denial, never permission. Everything *else* in this package degrades gracefully (§4.4); this
file is the one place that does not.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from core.auth.contracts import Role

from .contracts import AuthorizationResult
from .errors import AccessCheckUnavailable, CrossUserAccessDenied, GroupAccessDenied, code_for

#: Roles with system-wide visibility already, independent of any group or break-glass grant
#: (§4) — mirrors `core/groups/permission_gate.py`'s own `_SYSTEM_WIDE_ROLES` exactly, kept
#: as its own constant here rather than imported since it is a fact about Auth's own role
#: model, not a Groups-owned value.
_SYSTEM_WIDE_ROLES = (Role.OWNER, Role.STAFF)


@runtime_checkable
class CrossUserAccessChecker(Protocol):
    """The adapter seam onto Auth's break-glass ledger (`docs/PRINCIPLES.md` §1.3).

    Deliberately not an import of `core.auth`: this package holds no opinion about grants or
    roles, only about whether this caller may read this subject's receipts — the same
    reasoning `core/logs/query.py`'s own `AccessChecker` documents in full.
    """

    async def allow(self, requesting_user_id: str, target_user_id: str) -> bool:
        """`True` only for an active, unexpired break-glass grant covering exactly this
        pair. Raises rather than returning `False` if it genuinely cannot tell — the caller
        treats both as denial, but only one is worth an operator's attention."""


class DenyAllCrossUser:
    """The fail-closed default (`docs/PRINCIPLES.md` §4.2), not a placeholder to be replaced
    by something permissive — a Search/Query process running before Auth is reachable serves
    own-user reads only, the correct behaviour rather than a degraded one, the same posture
    `core/logs/query.py`'s own `DenyCrossUser` and `core/groups/permission_gate.py`'s own
    `DenyAllSessions` both take.
    """

    async def allow(self, requesting_user_id: str, target_user_id: str) -> bool:
        return False


class AuthBreakGlassChecker:
    """Adapts Auth's own `BreakGlassLedger.check_access` without importing it.

    `check` is supplied by whatever holds the Auth client — a callable (sync or async)
    taking `(staff_user_id, target_client_user_id)` and returning a bool, the exact signature
    `core.auth.break_glass.grant.BreakGlassLedger.check_access` already has. When Search/Query
    is wired into a real process, this is the one file that changes to call it directly.
    """

    def __init__(
        self, check: Callable[[str, str], Awaitable[bool] | bool]
    ) -> None:
        self._check = check

    async def allow(self, requesting_user_id: str, target_user_id: str) -> bool:
        try:
            result = self._check(requesting_user_id, target_user_id)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 - any failure here means "cannot tell"
            raise AccessCheckUnavailable(str(exc)) from exc
        return bool(result)


@runtime_checkable
class GroupManagerChecker(Protocol):
    """The adapter seam onto Groups' own live manager check and effective-group lookup.

    Two methods rather than one: `is_manager_over_group` answers `search_group()`'s own
    question directly (§4); `group_of` is what lets a single-target `search()` answer "does
    the requester manage a group the *target* belongs to" without this package re-deriving
    membership state of its own (`docs/PRINCIPLES.md` §3.4 — this is not a taxonomy or schema
    concern, it is delegating to the one API that already owns the answer).
    """

    async def is_manager_over_group(self, group_id: str, user_id: str) -> bool:
        """Live and uncached — see `core/groups/permission_gate.py`'s own `is_group_manager`,
        which the production adapter below calls directly on every invocation."""

    async def group_of(self, user_id: str) -> str | None:
        """The user's current effective group (`core/groups/effective_group.py`), or `None`
        if they belong to none. Used only to resolve *which* group a single-target search's
        manager check applies against."""


class DenyAllGroupManager:
    """The fail-closed default — a Search/Query process with no Groups client wired up grants
    no group-derived visibility at all, the correct behaviour rather than a degraded one."""

    async def is_manager_over_group(self, group_id: str, user_id: str) -> bool:
        return False

    async def group_of(self, user_id: str) -> str | None:
        return None


class GroupsPermissionGateAdapter:
    """The production wiring onto `core.groups.permission_gate.PermissionGate` and
    `core.groups.effective_group.EffectiveGroupResolver`.

    **Consumes both live, uncached — never caches or re-derives them**, per this package's
    own task scope and `core/groups/permission_gate.py`'s own docstring naming this exact
    consumer. Any exception from either — Groups unreachable, a malformed group id — is
    treated as "cannot tell" and therefore denial (`docs/PRINCIPLES.md` §4.2), never
    propagated to crash the caller.
    """

    def __init__(self, gate, effective) -> None:
        self._gate = gate
        self._effective = effective

    async def is_manager_over_group(self, group_id: str, user_id: str) -> bool:
        try:
            return bool(await self._gate.is_group_manager(group_id, user_id))
        except Exception:  # noqa: BLE001 - unreachable Groups means "cannot tell" -> deny
            return False

    async def group_of(self, user_id: str) -> str | None:
        try:
            result = await self._effective.get_effective_group(user_id)
        except Exception:  # noqa: BLE001 - unreachable Groups means "cannot tell" -> deny
            return None
        return result.group_id if result.ok else None


class SearchPermissionGate:
    """Every gated entry point Search/Query exposes goes through exactly one of these three
    methods. `structured_query.py` never re-derives an authorization decision of its own."""

    def __init__(
        self,
        *,
        cross_user: CrossUserAccessChecker | None = None,
        group_manager: GroupManagerChecker | None = None,
    ) -> None:
        self._cross_user: CrossUserAccessChecker = cross_user or DenyAllCrossUser()
        self._group_manager: GroupManagerChecker = group_manager or DenyAllGroupManager()

    async def authorize_search(
        self, target_user_id: str, requesting_user_id: str, requesting_role: Role
    ) -> AuthorizationResult:
        """§4's `search()` gate: own-user always allowed; otherwise staff/owner needs an
        active break-glass grant, and anyone else needs to manage a group the target belongs
        to. Neither path is checked for the other role — a client is never offered a
        break-glass path, and staff/owner never need group standing they already have
        system-wide."""
        if target_user_id == requesting_user_id:
            return AuthorizationResult(allowed=True)

        if requesting_role in _SYSTEM_WIDE_ROLES:
            try:
                allowed = await self._cross_user.allow(requesting_user_id, target_user_id)
            except AccessCheckUnavailable as exc:
                return AuthorizationResult(
                    allowed=False, error_code=code_for(exc), error_detail=str(exc)
                )
            if allowed:
                return AuthorizationResult(allowed=True)
            exc = CrossUserAccessDenied(
                f"no active break-glass grant for staff {requesting_user_id!r} "
                f"over client {target_user_id!r}"
            )
            return AuthorizationResult(
                allowed=False, error_code=code_for(exc), error_detail=str(exc)
            )

        group_id = await self._group_manager.group_of(target_user_id)
        if group_id is not None and await self._group_manager.is_manager_over_group(
            group_id, requesting_user_id
        ):
            return AuthorizationResult(allowed=True)
        exc = GroupAccessDenied(
            f"{requesting_user_id!r} is neither staff/owner-with-a-grant nor a group "
            f"manager over {target_user_id!r}"
        )
        return AuthorizationResult(allowed=False, error_code=code_for(exc), error_detail=str(exc))

    async def authorize_group_search(
        self, group_id: str, requesting_user_id: str, requesting_role: Role
    ) -> AuthorizationResult:
        """§4's `search_group()` gate: system-wide roles see any group; anyone else must be
        *that specific group's* own manager — never another group's manager, never
        break-glass, which does not apply to a group-scoped read at all."""
        if requesting_role in _SYSTEM_WIDE_ROLES:
            return AuthorizationResult(allowed=True)
        if await self._group_manager.is_manager_over_group(group_id, requesting_user_id):
            return AuthorizationResult(allowed=True)
        exc = GroupAccessDenied(
            f"{requesting_user_id!r} is not owner/staff and is not {group_id!r}'s own manager"
        )
        return AuthorizationResult(allowed=False, error_code=code_for(exc), error_detail=str(exc))

    async def authorize_aggregate(
        self,
        *,
        target_user_id: str | None,
        group_id: str | None,
        requesting_user_id: str,
        requesting_role: Role,
    ) -> AuthorizationResult:
        """§8's aggregate surface shares this API's own permission model rather than a
        second, parallel one — dispatching to whichever of the two gates above matches the
        request's own shape."""
        if group_id is not None:
            return await self.authorize_group_search(
                group_id, requesting_user_id, requesting_role
            )
        return await self.authorize_search(
            target_user_id or "", requesting_user_id, requesting_role
        )


__all__ = [
    "AuthBreakGlassChecker",
    "CrossUserAccessChecker",
    "DenyAllCrossUser",
    "DenyAllGroupManager",
    "GroupManagerChecker",
    "GroupsPermissionGateAdapter",
    "SearchPermissionGate",
]

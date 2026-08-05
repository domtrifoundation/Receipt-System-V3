"""Create/add/remove/manager-toggle (`v3-deepdive-41-groups.md` §3's own package layout).

This is the orchestration layer: validation, id generation, the audit hook — `store.py`
holds the raw SQL. Every public method returns a `contracts.py` result carrying
`error_code`/`error_detail`; nothing here raises across its own boundary
(`docs/PRINCIPLES.md` §4.1). This module does **not** decide who is allowed to call it —
that is `permission_gate.py`'s job, checked by the caller (`service.py`) before any of these
methods run. A test that wants to exercise "can staff add a member" composes both modules;
this one only answers "given that this call is authorized, what happens."

**The `is_group_manager` toggle gets an Audit entry — §11's own resolved open question.**
Flipping it is a real access-elevation action, the same class of decision Audit's own
`ActionType.GROUP_MANAGER_TOGGLED` and `PRIVILEGED_ACTIONS["is_group_manager_toggle"]` were
added for (`core/audit/contracts.py`). The hook is injected as a plain async callable rather
than importing `core.audit` directly, for the identical reason
`core/auth/break_glass/grant.py`'s own `AuditSink` is injected: this package must not take a
hard dependency on Audit being reachable, and the membership row this method just wrote is
itself durable evidence of the change even if the Audit call fails or no recorder is wired up
at all (`docs/PRINCIPLES.md` §4.4 — a failed audit *notification* degrades, it never undoes
or blocks the privileged action that already happened).
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from .contracts import (
    Group,
    GroupMembership,
    GroupResult,
    MembersListResult,
    MembershipResult,
    RemoveMembershipResult,
    utcnow,
)
from .errors import AlreadyAMember, GroupNotFound, InvalidGroupName, NotAMember, code_for
from .store import GroupsStore, in_thread

#: The seam onto Audit API (deep-dive §11). Signature matches
#: `core.audit.writer.AuditWriter.record_action` — `operation, actor_user_id, *,
#: target_user_id=None, reason=None, details=None`. `None` means "no recorder wired up yet",
#: the fail-*open* default for this specific hook and not a contradiction of §4.2: §4.2 is
#: about permission checks, and recording is not one — the toggle itself already happened by
#: the time this is called.
AuditRecorder = Callable[..., Awaitable[object]]

#: The canonical operation name `core.audit.contracts.PRIVILEGED_ACTIONS` maps to
#: `ActionType.GROUP_MANAGER_TOGGLED`. Kept as a constant here rather than a literal so the
#: two packages' own tests can both assert against the identical string.
GROUP_MANAGER_TOGGLE_OPERATION = "is_group_manager_toggle"


def new_group_id() -> str:
    return f"grp_{secrets.token_urlsafe(12)}"


class GroupMembershipService:
    """Owns `Group`/`GroupMembership` mutation. See the module docstring for what it does
    not own (authorization) and does (the Audit hook for §11's toggle)."""

    def __init__(self, store: GroupsStore, audit: AuditRecorder | None = None) -> None:
        self._store = store
        self._audit = audit

    # ------------------------------------------------------------- sync core
    # The synchronous methods are the real implementation, matching
    # `core/auth/session/session_store.py`'s own "sync core, async surface" shape — so tests
    # and any future Background Workers sweep can call this without an event loop, and there
    # is still exactly one place the SQL-adjacent logic lives.
    def create_group_sync(self, name: str, created_by: str) -> GroupResult:
        if not name or not name.strip():
            exc = InvalidGroupName("a group name must be non-empty")
            return GroupResult(ok=False, error_code=code_for(exc), error_detail=str(exc))
        group = Group(group_id=new_group_id(), name=name.strip(), created_by=created_by)
        self._store.insert_group(group)
        return GroupResult(ok=True, group=group)

    def add_member_sync(
        self, group_id: str, user_id: str, added_by: str, *, is_group_manager: bool = False,
    ) -> MembershipResult:
        if self._store.get_group(group_id) is None:
            exc = GroupNotFound(f"no such group {group_id!r}")
            return MembershipResult(ok=False, error_code=code_for(exc), error_detail=str(exc))
        if self._store.get_membership(group_id, user_id) is not None:
            exc = AlreadyAMember(f"{user_id!r} is already a member of {group_id!r}")
            return MembershipResult(ok=False, error_code=code_for(exc), error_detail=str(exc))
        membership = GroupMembership(
            group_id=group_id, user_id=user_id, is_group_manager=is_group_manager,
            joined_at=utcnow(), added_by=added_by,
        )
        self._store.insert_membership(membership)
        return MembershipResult(ok=True, membership=membership)

    def remove_member_sync(self, group_id: str, user_id: str) -> RemoveMembershipResult:
        removed = self._store.delete_membership(group_id, user_id)
        if not removed:
            exc = NotAMember(f"{user_id!r} is not a member of {group_id!r}")
            return RemoveMembershipResult(ok=False, error_code=code_for(exc), error_detail=str(exc))
        # A receipt cannot go on tagging to a group whose membership just ended — the active
        # selector must not silently keep resolving to a group this user has left (§7's live
        # re-check discipline, applied here rather than only at read time).
        self._store.clear_active_group_if(user_id, group_id)
        return RemoveMembershipResult(ok=True)

    def set_manager_flag_sync(
        self, group_id: str, user_id: str, is_manager: bool
    ) -> MembershipResult:
        changed = self._store.set_manager_flag(group_id, user_id, is_manager)
        if not changed:
            exc = NotAMember(f"{user_id!r} is not a member of {group_id!r}")
            return MembershipResult(ok=False, error_code=code_for(exc), error_detail=str(exc))
        membership = self._store.get_membership(group_id, user_id)
        return MembershipResult(ok=True, membership=membership)

    def list_members_sync(self, group_id: str) -> MembersListResult:
        if self._store.get_group(group_id) is None:
            exc = GroupNotFound(f"no such group {group_id!r}")
            return MembersListResult(ok=False, error_code=code_for(exc), error_detail=str(exc))
        return MembersListResult(ok=True, members=tuple(self._store.list_memberships_for_group(group_id)))

    # ---------------------------------------------------------- async surface
    async def create_group(self, name: str, created_by: str) -> GroupResult:
        return await in_thread(self.create_group_sync, name, created_by)

    async def add_member(
        self, group_id: str, user_id: str, added_by: str, *, is_group_manager: bool = False,
    ) -> MembershipResult:
        return await in_thread(
            self.add_member_sync, group_id, user_id, added_by,
            is_group_manager=is_group_manager,
        )

    async def remove_member(self, group_id: str, user_id: str) -> RemoveMembershipResult:
        return await in_thread(self.remove_member_sync, group_id, user_id)

    async def set_group_manager(
        self, group_id: str, user_id: str, is_manager: bool, *, actor_user_id: str,
        reason: str | None = None,
    ) -> MembershipResult:
        """§11: toggling `is_group_manager` is an access-elevation action and gets its own
        Audit entry, recorded *after* the write succeeds — the row is the fact, the Audit
        call is a notification about the fact, and a notification failing must never look
        like the fact itself failed to happen."""
        result = await in_thread(self.set_manager_flag_sync, group_id, user_id, is_manager)
        if result.ok and self._audit is not None:
            try:
                await self._audit(
                    GROUP_MANAGER_TOGGLE_OPERATION,
                    actor_user_id,
                    target_user_id=user_id,
                    reason=reason,
                    details={"group_id": group_id, "is_group_manager": is_manager},
                )
            except Exception:  # noqa: BLE001 - a degraded audit notification, never a failed toggle
                pass
        return result

    async def list_members(self, group_id: str) -> MembersListResult:
        return await in_thread(self.list_members_sync, group_id)


__all__ = [
    "GROUP_MANAGER_TOGGLE_OPERATION",
    "AuditRecorder",
    "GroupMembershipService",
    "new_group_id",
]

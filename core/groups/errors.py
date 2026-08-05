"""Groups error taxonomy.

These are surfaced as `error_code`/`error_detail` on the result contracts in `contracts.py`
rather than raised across this API's boundary (`docs/PRINCIPLES.md` §4.1). They exist as real
types because the *internal* call path still benefits from telling them apart — a caller
denied because their session will not resolve and a caller denied because they lack
`is_group_manager` on this specific group are different problems worth logging differently,
even though both surface identically to the RPC caller (`contracts.AuthorizationResult`).

Groups has no equivalent of Auth's raise-loudly carve-out. `permission_gate.py` is the one
place this package is deliberately *not* graceful: an unresolvable session, an unreachable
resolver, or an ambiguous membership state is always denied, never permitted
(`docs/PRINCIPLES.md` §4.2 — fail closed on security checks). Every other failure in this
package degrades to error data and nothing else (§4.4) — a caller adding an already-a-member
is told so, not crashed.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class GroupsError(Exception):
    """Base for everything this package raises internally, never across its boundary."""


class GroupNotFound(GroupsError):
    """The named `group_id` does not exist."""


class AlreadyAMember(GroupsError):
    """`add_member` called for a `(group_id, user_id)` pair that is already a membership row.

    Rejected rather than silently treated as a no-op: a second `AddGroupMember` naming a
    different `added_by` is a genuine question about who actually granted this visibility,
    and answering it by quietly keeping the first value would be exactly the kind of silent
    override `docs/PRINCIPLES.md` §4.3 rules out.
    """


class NotAMember(GroupsError):
    """`remove_member`, `set_group_manager`, or `set_active_group` named a user who does not
    currently belong to the group in question."""


class InvalidGroupName(GroupsError):
    """An empty or whitespace-only group name."""


class SessionUnresolvable(GroupsError):
    """The caller's session could not be resolved to a real identity — expired, revoked,
    unknown, or Auth itself unreachable. `permission_gate.py` treats all four identically:
    denied, never permitted (`docs/PRINCIPLES.md` §4.2)."""


class PermissionDenied(GroupsError):
    """A resolved, valid session that still lacks the privilege this call requires — not
    owner/staff, and not that specific group's own `is_group_manager` member."""


#: Stable wire codes for the `.proto` surface's own `error_code` field (§9). Field-only-append
#: discipline applies here the same way it does to the `.proto`: a code is added, never
#: renamed, because a client may be matching on it.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        GroupNotFound: "GROUP_NOT_FOUND",
        AlreadyAMember: "ALREADY_A_MEMBER",
        NotAMember: "NOT_A_MEMBER",
        InvalidGroupName: "INVALID_GROUP_NAME",
        SessionUnresolvable: "SESSION_UNRESOLVABLE",
        PermissionDenied: "PERMISSION_DENIED",
    }
)

#: Operator-facing one-liners, kept next to the codes so a client that only has the code
#: still has something to show (`docs/PRINCIPLES.md` §2.1.1 — a module-level lookup table
#: nothing should ever write is a `FrozenDict`, not a plain `dict`).
ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "GROUP_NOT_FOUND": "no such group exists",
        "ALREADY_A_MEMBER": "this user is already a member of this group",
        "NOT_A_MEMBER": "this user does not belong to this group",
        "INVALID_GROUP_NAME": "a group name must be non-empty",
        "SESSION_UNRESOLVABLE": "the caller's session could not be resolved; access denied",
        "PERMISSION_DENIED": (
            "the caller is not owner/staff and is not this group's own manager"
        ),
        "INTERNAL": "an unexpected internal error occurred",
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped.

    Unmapped is deliberately not an exception of its own: a caller receiving `INTERNAL` with
    a real detail string is strictly better off than one receiving a crash from the error
    path itself (the same posture `core/logs/errors.py`'s `code_for` takes).
    """
    return ERROR_CODES.get(type(exc), "INTERNAL")


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "AlreadyAMember",
    "GroupNotFound",
    "GroupsError",
    "InvalidGroupName",
    "NotAMember",
    "PermissionDenied",
    "SessionUnresolvable",
    "code_for",
]

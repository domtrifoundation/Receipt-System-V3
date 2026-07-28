"""Groups data contracts (`v3-deepdive-41-groups.md` §4, §9).

This is the only module in this package other packages import from (`docs/PRINCIPLES.md`
§1.1). Types and result shapes only — no SQL, no session resolution, no gRPC.

**This is not a §3.4 violation.** Architect API owns typed/learned/schema data — taxonomies,
vendor directories, anything a user or the system *teaches* the program. A `Group` and a
`GroupMembership` are identity/org-structure data, the same category Auth's own `User` and
`Session` already occupy (deep-dive §3), which is exactly why they live inside Auth's own
top-level database rather than inventing a fourth one (`docs/PRINCIPLES.md` §1.6). Nothing
here is a taxonomy a user teaches the system.

Every type is `@dataclass(frozen=True)` (`docs/PRINCIPLES.md` §2.1). None of them currently
holds a dict-typed field — membership is a flat, small relation, not a bag of arbitrary
key/values — so there is no `FrozenDict` field in this module today. If one is ever added
(a per-group settings blob, say), it must be a `FrozenDict`, never a plain `dict`, for the
identical shallow-immutability reason `core/logs/contracts.py` and `core/audit/contracts.py`
already document, and any `isinstance` check against it must test `collections.abc.Mapping`,
never `dict` — the Python 3.15 builtin `frozendict` is not a `dict` subclass.

**Errors are data at this boundary, never exceptions** (`docs/PRINCIPLES.md` §4.1). Groups has
no equivalent of Auth's raise-loudly carve-out for session/role failures: this package does not
resolve sessions itself (`permission_gate.py`'s `SessionResolver` does that, backed by Auth),
and by the time a call reaches any function here the caller has already been authorized or
denied. Every mutating or reading operation returns a result object carrying
`error_code`/`error_detail`, checked by the caller rather than raised across the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware UTC. Membership timestamps are compared against session and audit
    timestamps elsewhere in the cluster, so a naive value here would be the one thing that
    silently fails to line up (the same reasoning `core/logs/contracts.py` states in full)."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Group:
    """One team whose members' receipts get pooled for aggregate reporting (deep-dive §1).

    `created_by` is the owner or staff member who created it — group creation is a system
    administration action (§11 is silent on this specifically, but it is the same class of
    decision as the `is_group_manager` toggle it *does* resolve: an org-structure change, not
    a thing any group's own member can do to themselves). See `permission_gate.py`.
    """

    group_id: str
    name: str
    created_by: str
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class GroupMembership:
    """One user's standing, persistent membership in one group (deep-dive §4).

    `is_group_manager` is a **per-membership** flag, not a system-wide role (§4.1) — the same
    person can be a manager of one group and an ordinary member of another. `added_by` is kept
    for real audit value: who granted this specific, ongoing visibility relationship, distinct
    from the system-wide audit trail Audit API itself keeps for the *elevation* act (§11).
    """

    group_id: str
    user_id: str
    is_group_manager: bool
    joined_at: datetime
    added_by: str


# --------------------------------------------------------------------- results
# Errors are data at this API's boundary, never exceptions raised across it
# (`docs/PRINCIPLES.md` §4.1). Every result below carries `error_code`/`error_detail`; the
# error code strings themselves live in `errors.py`.


@dataclass(frozen=True)
class GroupResult:
    """The outcome of creating or fetching one `Group`."""

    ok: bool
    group: Group | None = None
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class MembershipResult:
    """The outcome of adding a member or toggling `is_group_manager`."""

    ok: bool
    membership: GroupMembership | None = None
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class RemoveMembershipResult:
    """The outcome of removing a member. No membership to hand back — it no longer exists."""

    ok: bool
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class MembersListResult:
    """§4.1's gated read: the current membership list for one group, or an error.

    `members` is empty and `ok` is `True` for a real, empty group — distinguishable from a
    denial only by `error_code` being unset, the same "empty is not an error" shape
    `LogQueryResult`/`AuditQueryResult` already use elsewhere in this project.
    """

    ok: bool
    members: tuple[GroupMembership, ...] = ()
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class EffectiveGroupResult:
    """§5's ingestion-time answer: which `group_id` (if any) a receipt should be stamped
    with. `group_id is None` with `ok=True` is the ordinary "this user is in no group at
    all" case, not a failure — Groups is additive and this is the ubiquitous common case
    (deep-dive §10's isolation-by-default test)."""

    ok: bool
    group_id: str | None = None
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class AuthorizationResult:
    """What `permission_gate.py` hands back for any gated call.

    `allowed=False` covers every denial reason uniformly — an unresolvable session, a
    resolved session lacking the right role or membership, and a resolver that raised are
    all indistinguishable from the caller's point of view, which is exactly the fail-closed
    property `docs/PRINCIPLES.md` §4.2 asks for: "cannot tell" and "not permitted" must
    produce the identical answer. `user_id` is populated whenever the session itself
    resolved, even on a denial, since a caller may reasonably log "denied for this user".
    """

    allowed: bool
    user_id: str | None = None
    error_code: str = ""
    error_detail: str = ""


__all__ = [
    "AuthorizationResult",
    "EffectiveGroupResult",
    "Group",
    "GroupMembership",
    "GroupResult",
    "MembershipResult",
    "MembersListResult",
    "RemoveMembershipResult",
    "utcnow",
]

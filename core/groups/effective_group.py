"""`get_effective_group()` — the ingestion-time hook (`v3-deepdive-41-groups.md` §5).

Called by Execution Core at ingestion time (its own deep-dive §6's checkpointing sequence is
the natural hook — the same "one chokepoint, not scattered calls" principle already applied
to Historian's narrative track, `v3-deepdive-29-historian.md` §5). Returns the user's own
explicitly-set "active group", or `None` if they belong to no group at all. The `group_id`
column itself lives on the receipt row in Persistence's own database (its deep-dive §1) —
this module supplies the value; Persistence just stores it faithfully (the "who decides vs.
who stores" boundary discipline the deep-dive names explicitly).

**§11's open question, resolved, and what "resolved" actually requires as code.** Multi-group
membership is real (a user can belong to more than one group), so a new receipt tags to "the
user's own explicitly-set active group — a simple selector, defaulting to whichever group
they most recently used — rather than an ambiguous auto-selection among several
memberships." That sentence names two things, not one, and both are implemented here:

1. **An explicit, persisted selector** (`store.group_active_selection`) — `set_active_group`
   below, callable by whatever surface eventually lets a user switch teams (the deep-dive's
   §11 third bullet resolves that surface to Interface's own dedicated group-management
   screen and the webapp's settings page, both outside this package's own gRPC surface, see
   this package's `CLAUDE.md`).
2. **A deterministic default before any explicit choice has ever been made**: bootstrapped to
   the most recently *joined* membership, which is the only reading of "most recently used"
   that does not depend on the thing it is bootstrapping (a "most recently used" that meant
   "most recently resolved by this very function" would have no answer the first time it is
   ever called for a given user). The bootstrap is `set_active_group`, called on the reading
   path from `get_effective_group` itself — the interpretation being pinned down once and
   made sticky is exactly what stops it from becoming an "ambiguous auto-selection" repeated
   differently on every subsequent call.

A removed membership cannot leave a stale active selection behind: `membership.py`'s
`remove_member` clears the pointer as part of the same removal, so this module never needs
to defend against reading one on its own.
"""

from __future__ import annotations

from .contracts import EffectiveGroupResult, utcnow
from .errors import NotAMember, code_for
from .store import GroupsStore, in_thread


class EffectiveGroupResolver:
    """The one class both RPCs behind §5 and §11 go through."""

    def __init__(self, store: GroupsStore) -> None:
        self._store = store

    # ------------------------------------------------------------- sync core
    def get_effective_group_sync(self, user_id: str) -> EffectiveGroupResult:
        active = self._store.get_active_group(user_id)
        if active is not None and self._store.get_membership(active, user_id) is not None:
            return EffectiveGroupResult(ok=True, group_id=active)

        # No selection, or a stale one pointing at a membership that no longer exists
        # (should already have been cleared by `remove_member`, but re-derived here too
        # rather than trusted blindly — this is a read path, and re-deriving the answer from
        # the current membership rows is what keeps it honest independent of that other
        # module's own bookkeeping).
        memberships = self._store.list_memberships_for_user(user_id)
        if not memberships:
            return EffectiveGroupResult(ok=True, group_id=None)

        # "Most recently used", bootstrapped: `list_memberships_for_user` orders by
        # `joined_at DESC`, so the first row is the most recently *joined* membership — the
        # only non-circular reading of "most recently used" available before any explicit
        # selection has ever been recorded. See the module docstring.
        chosen = memberships[0]
        self._store.set_active_group(user_id, chosen.group_id, utcnow())
        return EffectiveGroupResult(ok=True, group_id=chosen.group_id)

    def set_active_group_sync(self, user_id: str, group_id: str) -> EffectiveGroupResult:
        """The explicit selector. Requires an existing membership — a user cannot make an
        arbitrary group their active one just by naming it, which would let a receipt get
        tagged into a team's aggregate view the uploader was never actually added to."""
        if self._store.get_membership(group_id, user_id) is None:
            exc = NotAMember(f"{user_id!r} is not a member of {group_id!r}")
            return EffectiveGroupResult(ok=False, error_code=code_for(exc), error_detail=str(exc))
        self._store.set_active_group(user_id, group_id, utcnow())
        return EffectiveGroupResult(ok=True, group_id=group_id)

    # ---------------------------------------------------------- async surface
    async def get_effective_group(self, user_id: str) -> EffectiveGroupResult:
        return await in_thread(self.get_effective_group_sync, user_id)

    async def set_active_group(self, user_id: str, group_id: str) -> EffectiveGroupResult:
        return await in_thread(self.set_active_group_sync, user_id, group_id)


__all__ = ["EffectiveGroupResolver"]

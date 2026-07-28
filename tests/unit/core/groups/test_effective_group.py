"""`EffectiveGroupResolver` — §5's ingestion-time hook and §11's multi-group resolution.

§11 resolves multi-group membership as real ("a user can belong to more than one group") and
names the tagging rule precisely: "the user's own explicitly-set active group — a simple
selector, defaulting to whichever group they most recently used — rather than an ambiguous
auto-selection among several memberships." The tests below are the concrete cases that
sentence implies: what happens with zero, one, and several memberships; what "defaulting to
most recently used" means the very first time there is no prior usage to default to; and that
the default, once made, is *sticky* rather than silently recomputed on every call (the
"never an ambiguous auto-selection" half of the same sentence).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.groups.contracts import Group, GroupMembership
from core.groups.effective_group import EffectiveGroupResolver
from core.groups.membership import GroupMembershipService
from core.groups.store import GroupsStore

from .conftest import run


def utc(minutes_ago: float = 0.0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


def test_a_user_in_no_group_resolves_to_none_not_an_error(effective: EffectiveGroupResolver):
    """Deep-dive §10's isolation-by-default test: Groups is additive, so the ubiquitous case
    of "not in any group" must be a real, ordinary answer, not a failure."""
    result = run(effective.get_effective_group("nobody_1"))

    assert result.ok
    assert result.group_id is None


def test_a_single_membership_resolves_unambiguously(
    store: GroupsStore, effective: EffectiveGroupResolver,
):
    store.insert_group(Group("grp_1", "Team A", "owner_1"))
    store.insert_membership(GroupMembership("grp_1", "u1", False, utc(), "owner_1"))

    result = run(effective.get_effective_group("u1"))

    assert result.ok
    assert result.group_id == "grp_1"


def test_multiple_memberships_with_no_prior_selection_default_to_most_recently_joined(
    store: GroupsStore, effective: EffectiveGroupResolver,
):
    """The non-circular reading of "most recently used" before any explicit choice has ever
    been made: the membership that is freshest by `joined_at`, never an arbitrary or
    alphabetical pick among several equally-plausible memberships."""
    store.insert_group(Group("grp_old", "Old Team", "owner_1"))
    store.insert_group(Group("grp_new", "New Team", "owner_1"))
    store.insert_membership(
        GroupMembership("grp_old", "u1", False, utc(minutes_ago=1000), "owner_1")
    )
    store.insert_membership(
        GroupMembership("grp_new", "u1", False, utc(minutes_ago=1), "owner_1")
    )

    result = run(effective.get_effective_group("u1"))

    assert result.ok
    assert result.group_id == "grp_new"


def test_the_bootstrap_default_is_sticky_not_recomputed_on_every_call(
    store: GroupsStore, effective: EffectiveGroupResolver,
):
    """§11's own "never an ambiguous auto-selection" clause, made concrete: once a default has
    been resolved and persisted, joining a *third*, even more recent group must not silently
    flip the tag out from under receipts already being attributed to the first choice. A
    resolver that recomputed "most recent" on every call would make every new membership a
    silent retroactive change to where a user's uploads have been going."""
    store.insert_group(Group("grp_old", "Old Team", "owner_1"))
    store.insert_group(Group("grp_mid", "Mid Team", "owner_1"))
    store.insert_membership(
        GroupMembership("grp_old", "u1", False, utc(minutes_ago=1000), "owner_1")
    )
    store.insert_membership(
        GroupMembership("grp_mid", "u1", False, utc(minutes_ago=500), "owner_1")
    )
    first = run(effective.get_effective_group("u1"))
    assert first.group_id == "grp_mid"

    # A brand new, more recently joined membership arrives after the bootstrap already ran.
    store.insert_group(Group("grp_new", "New Team", "owner_1"))
    store.insert_membership(
        GroupMembership("grp_new", "u1", False, utc(minutes_ago=1), "owner_1")
    )

    second = run(effective.get_effective_group("u1"))

    assert second.group_id == "grp_mid"


def test_explicit_selection_overrides_the_bootstrap_default(
    store: GroupsStore, effective: EffectiveGroupResolver,
):
    store.insert_group(Group("grp_a", "Team A", "owner_1"))
    store.insert_group(Group("grp_b", "Team B", "owner_1"))
    store.insert_membership(GroupMembership("grp_a", "u1", False, utc(minutes_ago=100), "owner_1"))
    store.insert_membership(GroupMembership("grp_b", "u1", False, utc(minutes_ago=1), "owner_1"))
    run(effective.get_effective_group("u1"))  # bootstraps to grp_b

    switched = run(effective.set_active_group("u1", "grp_a"))

    assert switched.ok
    assert run(effective.get_effective_group("u1")).group_id == "grp_a"


def test_explicit_selection_of_a_group_the_user_does_not_belong_to_is_rejected(
    store: GroupsStore, effective: EffectiveGroupResolver,
):
    """A user cannot make an arbitrary group their active one just by naming it — that would
    let a receipt get tagged into a team's aggregate view the uploader was never added to."""
    store.insert_group(Group("grp_a", "Team A", "owner_1"))

    result = run(effective.set_active_group("u1", "grp_a"))

    assert not result.ok
    assert result.error_code == "NOT_A_MEMBER"


def test_removing_the_active_membership_clears_the_selector_and_recomputes(
    store: GroupsStore,
):
    """Integration across `membership.py` and `effective_group.py`: removal must not leave a
    stale pointer that keeps resolving to a group the user has actually left (deep-dive §7's
    live re-check discipline, applied to the selector rather than only to reads)."""
    service = GroupMembershipService(store)
    resolver = EffectiveGroupResolver(store)
    group_a = run(service.create_group("Team A", "owner_1")).group
    group_b = run(service.create_group("Team B", "owner_1")).group
    run(service.add_member(group_a.group_id, "u1", "owner_1"))
    run(service.add_member(group_b.group_id, "u1", "owner_1"))
    first = run(resolver.get_effective_group("u1"))  # bootstraps to whichever joined last

    run(service.remove_member(first.group_id, "u1"))
    after = run(resolver.get_effective_group("u1"))

    remaining = group_b.group_id if first.group_id == group_a.group_id else group_a.group_id
    assert after.ok
    assert after.group_id == remaining


def test_removing_a_non_active_membership_does_not_disturb_the_active_selection(
    store: GroupsStore,
):
    service = GroupMembershipService(store)
    resolver = EffectiveGroupResolver(store)
    group_a = run(service.create_group("Team A", "owner_1")).group
    group_b = run(service.create_group("Team B", "owner_1")).group
    run(service.add_member(group_a.group_id, "u1", "owner_1"))
    active = run(resolver.get_effective_group("u1"))
    assert active.group_id == group_a.group_id
    run(service.add_member(group_b.group_id, "u1", "owner_1"))

    run(service.remove_member(group_b.group_id, "u1"))
    after = run(resolver.get_effective_group("u1"))

    assert after.group_id == group_a.group_id


def test_removing_the_last_membership_resolves_back_to_no_group(store: GroupsStore):
    service = GroupMembershipService(store)
    resolver = EffectiveGroupResolver(store)
    group = run(service.create_group("Team A", "owner_1")).group
    run(service.add_member(group.group_id, "u1", "owner_1"))
    run(resolver.get_effective_group("u1"))

    run(service.remove_member(group.group_id, "u1"))
    after = run(resolver.get_effective_group("u1"))

    assert after.ok
    assert after.group_id is None

"""`GroupsStore`'s own raw CRUD (`v3-deepdive-41-groups.md` §3, §4).

These tests exercise `store.py` directly, underneath `membership.py`'s orchestration, so a
future change to the orchestration layer cannot accidentally hide a broken row-mapping or a
broken uniqueness constraint behind a passing higher-level test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.groups.contracts import Group, GroupMembership
from core.groups.store import GroupsStore


def utc(minutes_ago: float = 0.0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


def test_group_round_trips(store: GroupsStore):
    group = Group(group_id="grp_1", name="Team A", created_by="owner_1", created_at=utc())
    store.insert_group(group)

    fetched = store.get_group("grp_1")

    assert fetched == group


def test_unknown_group_is_none_not_an_error(store: GroupsStore):
    assert store.get_group("grp_missing") is None


def test_membership_round_trips(store: GroupsStore):
    store.insert_group(Group(group_id="grp_1", name="Team A", created_by="owner_1"))
    membership = GroupMembership(
        group_id="grp_1", user_id="client_1", is_group_manager=False, joined_at=utc(),
        added_by="owner_1",
    )
    store.insert_membership(membership)

    assert store.get_membership("grp_1", "client_1") == membership
    assert store.get_membership("grp_1", "someone_else") is None


def test_delete_membership_reports_whether_a_row_actually_existed(store: GroupsStore):
    store.insert_group(Group(group_id="grp_1", name="Team A", created_by="owner_1"))
    store.insert_membership(
        GroupMembership(
            group_id="grp_1", user_id="client_1", is_group_manager=False, joined_at=utc(),
            added_by="owner_1",
        )
    )

    assert store.delete_membership("grp_1", "client_1") is True
    assert store.delete_membership("grp_1", "client_1") is False
    assert store.get_membership("grp_1", "client_1") is None


def test_set_manager_flag_reports_false_for_a_non_member(store: GroupsStore):
    store.insert_group(Group(group_id="grp_1", name="Team A", created_by="owner_1"))

    assert store.set_manager_flag("grp_1", "never_added", True) is False


def test_set_manager_flag_flips_a_live_row(store: GroupsStore):
    store.insert_group(Group(group_id="grp_1", name="Team A", created_by="owner_1"))
    store.insert_membership(
        GroupMembership(
            group_id="grp_1", user_id="client_1", is_group_manager=False, joined_at=utc(),
            added_by="owner_1",
        )
    )

    changed = store.set_manager_flag("grp_1", "client_1", True)

    assert changed is True
    assert store.get_membership("grp_1", "client_1").is_group_manager is True


def test_list_memberships_for_group_is_scoped_to_that_group_only(store: GroupsStore):
    """§4.1's own scoping guarantee, tested at the storage layer directly: a group manager's
    (or, here, a bare query's) view must stop exactly at its own group's membership rows."""
    store.insert_group(Group(group_id="grp_1", name="Team A", created_by="owner_1"))
    store.insert_group(Group(group_id="grp_2", name="Team B", created_by="owner_1"))
    store.insert_membership(
        GroupMembership("grp_1", "a", False, utc(), "owner_1")
    )
    store.insert_membership(
        GroupMembership("grp_2", "b", False, utc(), "owner_1")
    )

    members = store.list_memberships_for_group("grp_1")

    assert [m.user_id for m in members] == ["a"]


def test_list_memberships_for_user_orders_most_recently_joined_first(store: GroupsStore):
    store.insert_group(Group(group_id="grp_old", name="Old", created_by="owner_1"))
    store.insert_group(Group(group_id="grp_new", name="New", created_by="owner_1"))
    store.insert_membership(
        GroupMembership("grp_old", "u1", False, utc(minutes_ago=100), "owner_1")
    )
    store.insert_membership(
        GroupMembership("grp_new", "u1", False, utc(minutes_ago=1), "owner_1")
    )

    memberships = store.list_memberships_for_user("u1")

    assert [m.group_id for m in memberships] == ["grp_new", "grp_old"]


def test_active_selection_round_trips_and_is_overwritable(store: GroupsStore):
    assert store.get_active_group("u1") is None

    store.set_active_group("u1", "grp_1", utc())
    assert store.get_active_group("u1") == "grp_1"

    store.set_active_group("u1", "grp_2", utc())
    assert store.get_active_group("u1") == "grp_2"


def test_clear_active_group_if_only_clears_a_matching_selection(store: GroupsStore):
    store.set_active_group("u1", "grp_1", utc())

    store.clear_active_group_if("u1", "grp_2")  # a different group — must not touch it
    assert store.get_active_group("u1") == "grp_1"

    store.clear_active_group_if("u1", "grp_1")
    assert store.get_active_group("u1") is None


def test_reopening_the_same_file_sees_prior_data(tmp_path):
    """Groups' own tables live in the same physical file Auth's own database opens
    (`store.py`'s module docstring) — this is the property that makes that safe: the schema
    is idempotent and a second connection to the same file sees what the first one wrote."""
    path = tmp_path / "auth.sqlite"
    first = GroupsStore(path)
    first.insert_group(Group(group_id="grp_1", name="Team A", created_by="owner_1"))
    first.close()

    second = GroupsStore(path)
    try:
        assert second.get_group("grp_1") is not None
    finally:
        second.close()

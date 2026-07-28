"""Frozen-contract guarantees, and the error-taxonomy coverage check.

Mirrors `tests/unit/core/audit/test_metrics_and_contracts.py`'s own shape: every result type
crossing this API's boundary must actually be frozen, and every wire error code this package
can produce must have a human-readable summary behind it.
"""

from __future__ import annotations

import collections.abc
import dataclasses
from datetime import datetime, timezone

import pytest

from common.frozen_dict import FrozenDict
from core.groups import errors
from core.groups.contracts import (
    AuthorizationResult,
    EffectiveGroupResult,
    Group,
    GroupMembership,
    GroupResult,
    MembershipResult,
    MembersListResult,
    RemoveMembershipResult,
)


@pytest.mark.parametrize(
    "cls",
    [
        Group,
        GroupMembership,
        GroupResult,
        MembershipResult,
        RemoveMembershipResult,
        MembersListResult,
        EffectiveGroupResult,
        AuthorizationResult,
    ],
)
def test_every_contract_is_frozen(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen, f"{cls.__name__} crosses a boundary unfrozen"


def test_group_and_membership_cannot_be_mutated_after_construction():
    """The concrete case the parametrised check above is a proxy for: an actual attempt to
    write a field must raise, not silently succeed."""
    now = datetime.now(timezone.utc)
    group = Group(group_id="grp_1", name="Team A", created_by="owner_1", created_at=now)
    membership = GroupMembership(
        group_id="grp_1", user_id="client_1", is_group_manager=False, joined_at=now,
        added_by="owner_1",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        group.name = "Team B"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        membership.is_group_manager = True  # type: ignore[misc]


def test_group_created_at_defaults_to_a_real_timezone_aware_timestamp():
    group = Group(group_id="grp_1", name="Team A", created_by="owner_1")
    assert group.created_at.tzinfo is not None


def test_empty_results_are_not_errors():
    """The "empty is not a failure" shape `LogQueryResult`/`AuditQueryResult` already use:
    `ok=True` with nothing in it must be distinguishable from a denial only by `error_code`."""
    empty_list = MembersListResult(ok=True)
    assert empty_list.ok and empty_list.members == () and not empty_list.error_code

    no_group = EffectiveGroupResult(ok=True, group_id=None)
    assert no_group.ok and no_group.group_id is None and not no_group.error_code


# -------------------------------------------------------------------- errors


def test_every_error_code_has_a_summary():
    codes = set(errors.ERROR_CODES.values())
    assert codes <= set(errors.ERROR_SUMMARIES)


def test_code_for_maps_every_declared_exception():
    for exc_type, code in errors.ERROR_CODES.items():
        assert errors.code_for(exc_type("detail")) == code


def test_code_for_falls_back_to_internal_for_anything_unmapped():
    class SomeOtherError(Exception):
        pass

    assert errors.code_for(SomeOtherError()) == "INTERNAL"
    assert "INTERNAL" in errors.ERROR_SUMMARIES


# ------------------------------------------------------------- forward compat


@pytest.mark.forward_compat
def test_module_level_lookup_tables_are_frozen_dicts():
    """`docs/PRINCIPLES.md` §2.1.1 — a table every module reads and nothing should ever
    write, shared across real OS threads under free-threading. Asserted against `Mapping`
    plus a real mutation attempt rather than against `dict`, because the Python 3.15 builtin
    `frozendict` is not a `dict` subclass and a bare `dict` check would pass on 3.14 and
    silently fail on 3.15 — the exact gotcha `common/frozen_dict.py` documents.

    `contracts.py` itself declares no `FrozenDict`-typed field today (Groups' own data model
    is a flat relation, not a bag of arbitrary key/values — see that module's own docstring),
    so this test targets `errors.py`'s two lookup tables, the only `FrozenDict` instances this
    package currently has.
    """
    for table in (errors.ERROR_CODES, errors.ERROR_SUMMARIES):
        assert isinstance(table, collections.abc.Mapping)
        assert type(table) is FrozenDict
        with pytest.raises(TypeError):
            table["injected"] = "value"  # type: ignore[index]


@pytest.mark.forward_compat
def test_contracts_module_has_no_frozen_dict_field_to_get_wrong():
    """A guard against silent drift: if a future change adds a dict-typed field to any
    contract in this module, it must be a `FrozenDict`, never a plain `dict` — this test
    documents *why* there is nothing to check here today rather than leaving the absence
    unexplained, so the next session that adds such a field knows to add the check here too."""
    for cls in (Group, GroupMembership, GroupResult, MembershipResult, RemoveMembershipResult,
                MembersListResult, EffectiveGroupResult, AuthorizationResult):
        for f in dataclasses.fields(cls):
            assert f.type != "dict", (
                f"{cls.__name__}.{f.name} is a plain dict-typed field — it must be a "
                f"FrozenDict per docs/PRINCIPLES.md §2.1, and this test needs updating to "
                f"assert its immutability"
            )

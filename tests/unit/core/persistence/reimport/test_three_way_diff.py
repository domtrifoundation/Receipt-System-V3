"""The three-way resolution matrix — Reimport's own §8 first named testing hook.

Every combination of (user changed / did not) × (canonical changed / did not) against the
expected outcome. The deep-dive is explicit that this is validated rather than "trusted from
the code reading correctly once," which is what the exhaustive parametrization below is for.
"""

from __future__ import annotations

import pytest

from common.frozen_dict import FrozenDict
from core.persistence.reimport.three_way_diff import three_way_resolve


def _resolve(original, canonical, reimported):
    return three_way_resolve(
        FrozenDict({"f": original}),
        FrozenDict({"f": canonical}),
        FrozenDict({"f": reimported}),
        receipt_id="rc1",
    )


def test_user_did_not_touch_it_so_canonical_wins():
    """A stale export must never silently revert a newer correction."""
    outcome = _resolve("base", "corrected-since-export", "base")
    assert outcome.resolved["f"] == "corrected-since-export"
    assert outcome.conflicts == ()
    assert outcome.applied_fields == ()


def test_only_the_user_changed_it_so_it_applies_cleanly():
    outcome = _resolve("base", "base", "user-edit")
    assert outcome.resolved["f"] == "user-edit"
    assert outcome.conflicts == ()
    assert outcome.applied_fields == ("f",)


def test_both_changed_differently_is_a_genuine_conflict():
    """Never resolved automatically. Canonical stays authoritative until a human decides."""
    outcome = _resolve("base", "canonical-edit", "user-edit")
    assert outcome.resolved["f"] == "canonical-edit"
    assert outcome.applied_fields == ()
    assert len(outcome.conflicts) == 1
    conflict = outcome.conflicts[0]
    assert conflict.field == "f"
    assert conflict.original_value == "base"
    assert conflict.canonical_value == "canonical-edit"
    assert conflict.reimported_value == "user-edit"
    assert conflict.receipt_id == "rc1"


def test_both_changed_to_the_same_value_is_not_a_conflict():
    """There is nothing for a human to decide, and flagging it would flood the queue with
    decisions that have only one possible answer."""
    outcome = _resolve("base", "agreed", "agreed")
    assert outcome.resolved["f"] == "agreed"
    assert outcome.conflicts == ()


def test_nothing_changed_anywhere():
    outcome = _resolve("base", "base", "base")
    assert outcome.resolved["f"] == "base"
    assert outcome.conflicts == ()
    assert outcome.applied_fields == ()


def test_a_field_absent_from_the_reimport_is_left_alone():
    """Not carrying a field is not the same as asking to clear it."""
    outcome = three_way_resolve(
        FrozenDict({"a": 1, "b": 2}), FrozenDict({"a": 1, "b": 99}), FrozenDict({"a": 1})
    )
    assert "b" not in outcome.resolved
    assert outcome.conflicts == ()


def test_one_conflict_does_not_block_the_other_fields():
    """No rejecting a whole reimport over one conflicting field."""
    outcome = three_way_resolve(
        FrozenDict({"a": "base", "b": "base"}),
        FrozenDict({"a": "base", "b": "canonical"}),
        FrozenDict({"a": "user", "b": "user"}),
    )
    assert outcome.resolved["a"] == "user"
    assert outcome.applied_fields == ("a",)
    assert [c.field for c in outcome.conflicts] == ["b"]


def test_result_is_a_frozen_dict():
    outcome = _resolve("base", "base", "edit")
    assert isinstance(outcome.resolved, FrozenDict)


def test_non_mapping_arguments_are_rejected_loudly():
    with pytest.raises(TypeError):
        three_way_resolve([], FrozenDict({}), FrozenDict({}))  # type: ignore[arg-type]

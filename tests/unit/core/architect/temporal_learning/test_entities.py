"""The three-entity model (`v3-deepdive-40-temporal-learning.md` §4, §11).

The centrepiece is the deep-dive's own **franchiser reference-not-duplication test**: two
branches under two different corporations, both referencing the same franchiser, and a TIN
correction applied once being reflected by both. That scenario is the entire reason
`Franchiser` is a standalone entity instead of fields on a branch row, so it is the test
that fails first if anyone ever flattens the model back.
"""

from __future__ import annotations

import asyncio

from core.architect.temporal_learning.contracts import VendorLayer
from core.architect.temporal_learning.errors import LearningErrorCode


def _global_corporation(pipeline, name, tin, staff="staff-1"):
    asyncio.run(
        pipeline.layering.staff_create_global(
            "corporation", {"name": name, "corporate_tin": tin}, staff_user_id=staff
        )
    )
    return next(
        e for e in pipeline.entities.store.all_of("corporation") if e.name == name
    ).corporation_id


def test_one_franchiser_operating_two_corporations_branches_is_corrected_once(pipeline):
    """The franchiser reference-not-duplication test."""
    burger_id = _global_corporation(pipeline, "Burger Chain PH", "111-111-111")
    chicken_id = _global_corporation(pipeline, "Chicken Chain PH", "222-222-222")

    franchiser = pipeline.entities.create(
        "franchiser",
        {"name": "Santos Family Holdings", "franchiser_tin": "333-333-333"},
        actor_user_id="user-1",
    ).entity

    branch_a = pipeline.entities.create(
        "branch",
        {"corporation_id": burger_id, "address": "12 Rizal Ave", "franchiser_id": franchiser.franchiser_id},
        actor_user_id="user-1",
    ).entity
    branch_b = pipeline.entities.create(
        "branch",
        {"corporation_id": chicken_id, "address": "9 Bonifacio St", "franchiser_id": franchiser.franchiser_id},
        actor_user_id="user-1",
    ).entity

    # The correction is applied once, to the one franchiser record.
    corrected = pipeline.entities.update(
        "franchiser", franchiser.franchiser_id, {"franchiser_tin": "444-444-444"},
        actor_user_id="user-1",
    )
    assert corrected.ok

    for branch_id in (branch_a.branch_id, branch_b.branch_id):
        _, corporation, resolved_franchiser = pipeline.entities.resolve_branch(branch_id)
        assert resolved_franchiser is not None
        assert resolved_franchiser.franchiser_tin == "444-444-444"
        assert corporation is not None

    # Two branches, two corporations, one franchiser — never two copies of the same one.
    assert len(pipeline.entities.store.all_of("franchiser")) == 1
    assert len(pipeline.entities.branches_of_franchiser(franchiser.franchiser_id)) == 2


def test_a_branch_may_permanently_have_no_franchiser(pipeline):
    """Corporate-owned branches are a legitimate end state, not an unfilled field."""
    corporation_id = _global_corporation(pipeline, "Corporate Chain", "555-555-555")
    branch = pipeline.entities.create(
        "branch", {"corporation_id": corporation_id, "address": "1 Ayala Ave"},
        actor_user_id="user-1",
    ).entity
    assert branch.franchiser_id is None
    _, _, franchiser = pipeline.entities.resolve_branch(branch.branch_id)
    assert franchiser is None


def test_a_branch_referencing_a_missing_entity_is_refused(pipeline):
    result = pipeline.entities.create(
        "branch", {"corporation_id": "corp-does-not-exist", "address": "1 Nowhere"},
        actor_user_id="user-1",
    )
    assert result.error is not None
    assert result.error.code == LearningErrorCode.INVALID_REFERENCE


def test_create_always_produces_a_local_unshared_entity_whatever_is_passed(pipeline):
    """No argument to this method can produce a global entity."""
    entity = pipeline.entities.create(
        "corporation",
        {"name": "Sneaky", "corporate_tin": "1", "layer": VendorLayer.GLOBAL, "shared": True},
        actor_user_id="user-1",
    ).entity
    assert entity.layer is VendorLayer.LOCAL
    assert entity.shared is False


def test_missing_required_fields_are_refused(pipeline):
    result = pipeline.entities.create("corporation", {"name": "No TIN"}, actor_user_id="user-1")
    assert result.error is not None
    assert result.error.code == LearningErrorCode.INVALID_CHANGE


def test_unknown_entity_type_is_data_not_an_exception(pipeline):
    result = pipeline.entities.create("vendor", {"name": "x"}, actor_user_id="user-1")
    assert result.error is not None
    assert result.error.code == LearningErrorCode.UNKNOWN_ENTITY_TYPE


def test_local_entities_are_visible_only_to_their_own_owner(pipeline):
    pipeline.entities.create(
        "corporation", {"name": "Mine", "corporate_tin": "1"}, actor_user_id="user-1"
    )
    assert [e.name for e in pipeline.entities.list_visible("corporation", "user-1").entities] == ["Mine"]
    assert pipeline.entities.list_visible("corporation", "user-2").entities == ()
    assert pipeline.entities.list_visible("corporation", None).entities == ()

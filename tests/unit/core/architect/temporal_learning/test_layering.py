"""The sharing gate and the two promotion paths (`v3-deepdive-40-temporal-learning.md` §11).

Three of the deep-dive's own named testing hooks live here:

- **Sharing-gate test** — a `LOCAL`, unshared entity is never picked up by the moderation
  queue on its own; only an explicit `share_entity` call creates a contribution at all.
- **Layer-promotion gate test** — a user-shared contribution never becomes visible to
  another user without an explicit staff approval.
- **Staff direct-to-global test** — a staff-authored contribution merges after prescreen
  alone, with no second staff member's approval, while still landing a recorded event.
"""

from __future__ import annotations

import asyncio

from core.architect.temporal_learning.contracts import VendorLayer
from core.architect.temporal_learning.errors import LearningErrorCode


def _local_corporation(pipeline, user="user-1", name="Aling Nena Sari-Sari"):
    result = pipeline.entities.create(
        "corporation", {"name": name, "corporate_tin": "123-456-789"}, actor_user_id=user
    )
    assert result.ok
    return result.entity


def test_a_local_entity_is_created_with_no_review_at_all(pipeline):
    """§3: a private fact cannot hurt anyone but its own user, so it is written freely."""
    entity = _local_corporation(pipeline)
    assert entity.layer is VendorLayer.LOCAL
    assert entity.shared is False
    assert pipeline.queue.all() == ()


def test_local_entity_never_enters_the_queue_on_its_own(pipeline):
    """The sharing-gate test. Existing is not consenting."""
    _local_corporation(pipeline)
    _local_corporation(pipeline, name="Another Store")
    assert pipeline.queue.all() == ()
    assert pipeline.queue.pending() == ()


def test_share_entity_is_what_creates_a_contribution(pipeline):
    entity = _local_corporation(pipeline)
    result = asyncio.run(
        pipeline.layering.share_entity("corporation", entity.corporation_id, "user-1")
    )
    assert result.ok
    assert len(pipeline.queue.all()) == 1
    contribution = result.contribution
    assert contribution.contributor == "human:user-1"
    assert contribution.staff_review_status == "pending"
    # The share is recorded on the entity itself, so consent is a fact, not a moment.
    assert pipeline.entities.get("corporation", entity.corporation_id).entity.shared is True


def test_sharing_someone_elses_local_entity_is_refused(pipeline):
    entity = _local_corporation(pipeline, user="user-1")
    result = asyncio.run(
        pipeline.layering.share_entity("corporation", entity.corporation_id, "user-2")
    )
    assert not result.ok
    assert pipeline.queue.all() == ()


def test_sharing_twice_is_refused(pipeline):
    entity = _local_corporation(pipeline)
    asyncio.run(pipeline.layering.share_entity("corporation", entity.corporation_id, "user-1"))
    again = asyncio.run(
        pipeline.layering.share_entity("corporation", entity.corporation_id, "user-1")
    )
    assert again.error is not None and again.error.code == LearningErrorCode.ALREADY_SHARED
    assert len(pipeline.queue.all()) == 1


def test_shared_contribution_is_invisible_to_others_until_staff_approve(pipeline):
    """The layer-promotion gate test."""
    entity = _local_corporation(pipeline)
    shared = asyncio.run(
        pipeline.layering.share_entity("corporation", entity.corporation_id, "user-1")
    )
    contribution_id = shared.contribution.contribution_id

    asyncio.run(pipeline.queue.prescreen(contribution_id))
    refused = pipeline.queue.merge(contribution_id)
    assert refused.error is not None
    assert refused.error.code == LearningErrorCode.APPROVAL_REQUIRED
    assert pipeline.entities.list_visible("corporation", "user-2").entities == ()

    pipeline.queue.review(contribution_id, reviewer="staff-1", approved=True)
    merged = pipeline.queue.merge(contribution_id)
    assert merged.ok and merged.contribution.merged

    visible = pipeline.entities.list_visible("corporation", "user-2").entities
    assert [e.layer for e in visible] == [VendorLayer.GLOBAL]
    assert visible[0].name == entity.name


def test_rejected_contribution_never_reaches_the_global_layer(pipeline):
    entity = _local_corporation(pipeline)
    shared = asyncio.run(
        pipeline.layering.share_entity("corporation", entity.corporation_id, "user-1")
    )
    contribution_id = shared.contribution.contribution_id
    asyncio.run(pipeline.queue.prescreen(contribution_id))
    pipeline.queue.review(contribution_id, reviewer="staff-1", approved=False, reason="wrong TIN")

    refused = pipeline.queue.merge(contribution_id)
    assert refused.error is not None
    assert refused.error.code == LearningErrorCode.APPROVAL_REQUIRED
    assert pipeline.entities.list_visible("corporation", "user-2").entities == ()


def test_staff_direct_to_global_merges_after_prescreen_alone(pipeline):
    """The staff direct-to-global test — a shorter path, not a quieter one."""
    result = asyncio.run(
        pipeline.layering.staff_create_global(
            "corporation",
            {"name": "Corporate Chain", "corporate_tin": "999-888-777"},
            staff_user_id="staff-1",
        )
    )
    assert result.ok
    contribution = result.contribution
    assert contribution.staff_review_status == "not_applicable"
    assert contribution.merged is True
    assert contribution.prescreened

    visible = pipeline.entities.list_visible("corporation", "user-2").entities
    assert [e.name for e in visible] == ["Corporate Chain"]

    events = {e.event for e in pipeline.queue.mirror.for_contribution(contribution.contribution_id)}
    assert events == {"submitted", "prescreened", "merged"}
    submitted = pipeline.queue.mirror.for_contribution(contribution.contribution_id)[0]
    assert submitted.actor == "human:staff-1"


def test_a_staff_path_contribution_cannot_also_be_reviewed(pipeline):
    """Neither path silently adopts the other's rule."""
    result = asyncio.run(
        pipeline.layering.staff_create_global(
            "corporation", {"name": "Corporate Chain", "corporate_tin": "999-888-777"},
            staff_user_id="staff-1",
        )
    )
    review = pipeline.queue.review(
        result.contribution.contribution_id, reviewer="staff-2", approved=False
    )
    assert review.error is not None
    assert review.error.code == LearningErrorCode.STAFF_ROLE_REQUIRED


def test_editing_a_global_entity_directly_is_refused(pipeline):
    """Correcting shared truth is a contribution, never an ordinary edit."""
    created = asyncio.run(
        pipeline.layering.staff_create_global(
            "corporation", {"name": "Corporate Chain", "corporate_tin": "999-888-777"},
            staff_user_id="staff-1",
        )
    )
    entity_id = pipeline.entities.list_visible("corporation", None).entities[0].corporation_id
    assert created.ok

    result = pipeline.entities.update(
        "corporation", entity_id, {"name": "Renamed"}, actor_user_id="user-1"
    )
    assert result.error is not None
    assert result.error.code == LearningErrorCode.APPROVAL_REQUIRED


def test_a_shared_branch_cannot_land_globally_pointing_at_a_local_corporation(pipeline):
    """A global reference has to resolve for whoever can see the referrer.

    Sharing a branch on its own used to promote it to `GLOBAL` while its `corporation_id`
    still named the contributor's own `LOCAL` corporation — so every other user saw a
    global branch whose corporation `list_visible` hid from them and `resolve_branch`
    returned `None` for. The reference model §4 exists to protect is worth nothing if the
    thing on the far end of the reference is unreachable.
    """
    corp = _local_corporation(pipeline)
    branch = pipeline.entities.create(
        "branch",
        {"corporation_id": corp.corporation_id, "address": "123 Real St"},
        actor_user_id="user-1",
    ).entity
    shared = asyncio.run(
        pipeline.layering.share_entity("branch", branch.branch_id, "user-1")
    )
    contribution_id = shared.contribution.contribution_id
    asyncio.run(pipeline.queue.prescreen(contribution_id))
    pipeline.queue.review(contribution_id, "staff-1", True)

    refused = pipeline.queue.merge(contribution_id)
    assert refused.error is not None
    assert refused.error.code == LearningErrorCode.INVALID_REFERENCE
    assert [b.layer for b in pipeline.entities.store.all_of("branch")] == [VendorLayer.LOCAL]
    assert pipeline.entities.list_visible("branch", "user-2").entities == ()


def test_a_staff_correction_cannot_reassign_ownership_of_a_global_entity(pipeline):
    """`owner_user_id` is placement, not a fact — a contribution may not carry it."""
    asyncio.run(
        pipeline.layering.staff_create_global(
            "corporation", {"name": "Corporate Chain", "corporate_tin": "999"},
            staff_user_id="staff-1",
        )
    )
    entity_id = pipeline.entities.list_visible("corporation", None).entities[0].corporation_id
    asyncio.run(
        pipeline.layering.staff_update_global(
            "corporation", entity_id, {"name": "Renamed", "owner_user_id": "attacker"},
            staff_user_id="staff-1",
        )
    )
    updated = pipeline.entities.get("corporation", entity_id).entity
    assert updated.name == "Renamed"
    assert updated.owner_user_id is None

"""Curate (`v3-deepdive-40-temporal-learning.md` §7, §11).

The deep-dive's own hook: **every `CurationCandidate` type lands in the pending-review
queue and never directly mutates the live directory.** All three types are covered, and
the "never auto-applies" assertion is repeated per type on purpose — a shortcut added for
one candidate type later is exactly the failure this hook exists to catch.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from core.architect.temporal_learning.contracts import Corporation, VendorLayer, utcnow
from core.architect.temporal_learning.curate import (
    ABANDONED_REVIEW_DAYS,
    Curator,
    find_abandoned_reviews,
    find_low_confidence_stale,
    find_near_duplicates,
)
from core.architect.temporal_learning.contribution import contribution_for_correction


def _old_local(pipeline, name, days_old=400):
    entity = pipeline.entities.create(
        "corporation", {"name": name, "corporate_tin": "1"}, actor_user_id="user-1"
    ).entity
    from dataclasses import replace

    aged = replace(entity, created_at=utcnow() - timedelta(days=days_old))
    pipeline.entities.store.put(aged)
    return aged


def test_stale_local_entries_are_found(pipeline):
    aged = _old_local(pipeline, "Forgotten Store")
    fresh = pipeline.entities.create(
        "corporation", {"name": "Recent Store", "corporate_tin": "2"}, actor_user_id="user-1"
    ).entity
    candidates = find_low_confidence_stale(
        pipeline.entities.store.all_of("corporation"), observation_counts={}
    )
    ids = {c.target_entries[0] for c in candidates}
    assert aged.corporation_id in ids
    assert fresh.corporation_id not in ids


def test_a_well_confirmed_stale_entry_is_left_alone(pipeline):
    aged = _old_local(pipeline, "Busy Store")
    candidates = find_low_confidence_stale(
        pipeline.entities.store.all_of("corporation"),
        observation_counts={aged.corporation_id: 42},
    )
    assert candidates == ()


def test_global_entries_are_never_proposed_for_pruning(pipeline):
    entity = Corporation(
        corporation_id="corp-global", name="Approved Chain", corporate_tin="9",
        layer=VendorLayer.GLOBAL, shared=True,
        created_at=utcnow() - timedelta(days=999),
    )
    pipeline.entities.store.put(entity)
    assert find_low_confidence_stale((entity,), observation_counts={}) == ()


def test_near_duplicates_are_found_by_normalized_name_without_a_scorer(pipeline):
    pipeline.entities.create(
        "corporation", {"name": "Metro Mart Inc.", "corporate_tin": "1"}, actor_user_id="user-1"
    )
    pipeline.entities.create(
        "corporation", {"name": "Metro Mart", "corporate_tin": "1"}, actor_user_id="user-1"
    )
    candidates = find_near_duplicates(pipeline.entities.store.all_of("corporation"))
    assert len(candidates) == 1
    assert len(candidates[0].target_entries) == 2


def test_near_duplicate_detection_accepts_matchings_own_scorer(pipeline):
    """Similarity is supplied through a seam; this module never scores fuzzily itself."""
    pipeline.entities.create(
        "corporation", {"name": "Alpha", "corporate_tin": "1"}, actor_user_id="user-1"
    )
    pipeline.entities.create(
        "corporation", {"name": "Beta", "corporate_tin": "2"}, actor_user_id="user-1"
    )
    everything_matches = find_near_duplicates(
        pipeline.entities.store.all_of("corporation"), scorer=lambda a, b: 1.0
    )
    assert len(everything_matches) == 1


def test_abandoned_reviews_are_surfaced_after_the_resolved_window(pipeline):
    from dataclasses import replace

    built = contribution_for_correction(
        "corporation", None, {"name": "Waiting", "corporate_tin": "1"}, "worker"
    ).contribution
    aged = replace(
        built, submitted_at=utcnow() - timedelta(days=ABANDONED_REVIEW_DAYS + 1)
    )
    pipeline.queue.submit(aged)

    candidates = find_abandoned_reviews(pipeline.queue)
    assert [c.candidate_type for c in candidates] == ["abandoned_pending_review"]
    # Surfaced only — never decided on the contribution's behalf.
    assert pipeline.queue.get(aged.contribution_id).contribution.staff_review_status == "pending"


def test_curate_never_applies_anything_it_finds(pipeline):
    """The load-bearing assertion: staging, not applying, for every candidate type."""
    aged = _old_local(pipeline, "Metro Mart Inc.")
    _old_local(pipeline, "Metro Mart")
    from dataclasses import replace

    built = contribution_for_correction(
        "corporation", None, {"name": "Waiting", "corporate_tin": "1"}, "worker"
    ).contribution
    pipeline.queue.submit(
        replace(built, submitted_at=utcnow() - timedelta(days=ABANDONED_REVIEW_DAYS + 1))
    )

    before = {c.corporation_id for c in pipeline.entities.store.all_of("corporation")}
    curator = Curator(pipeline.entities, pipeline.queue)
    staged = curator.propose_all()

    assert {c.candidate_type for c in curator.scan().candidates} == {
        "low_confidence_stale", "near_duplicate_merge", "abandoned_pending_review",
    }
    assert staged
    assert all(c.staff_review_status == "pending" and not c.merged for c in staged)
    # Nothing was pruned, merged or otherwise touched.
    after = {c.corporation_id for c in pipeline.entities.store.all_of("corporation")}
    assert after == before
    assert aged.corporation_id in after


def test_an_approved_curation_candidate_still_touches_no_entity(pipeline):
    """Approval decides the *candidate*; the follow-up is its own staged contribution."""
    _old_local(pipeline, "Forgotten Store")
    curator = Curator(pipeline.entities, pipeline.queue)
    staged = curator.propose_all()
    candidate = staged[0]

    asyncio.run(pipeline.queue.prescreen(candidate.contribution_id))
    pipeline.queue.review(candidate.contribution_id, "staff-1", approved=True)
    merged = pipeline.queue.merge(candidate.contribution_id)

    assert merged.ok
    assert len(pipeline.entities.store.all_of("corporation")) == 1

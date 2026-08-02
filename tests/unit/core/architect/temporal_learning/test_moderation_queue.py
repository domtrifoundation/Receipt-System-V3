"""The moderation pipeline's gates (`v3-deepdive-26-architect-api.md` §8, `-40` §6, §11).

Architect's own deep-dive §8 names one hook directly: "confirms a contribution never
reaches the live directory without passing through both prescreen and staff approval — no
shortcut path." That is what most of this file is. The unavailable-prescreen case is the
one worth reading twice: this API degrades gracefully almost everywhere, and here it
deliberately does not — an unavailable screen makes review take longer, never makes it
optional.
"""

from __future__ import annotations

import asyncio

from common.frozen_dict import FrozenDict
from core.architect.temporal_learning.contribution import contribution_for_correction
from core.architect.temporal_learning.errors import LearningErrorCode
from core.architect.temporal_learning.moderation_queue import (
    HeuristicPrescreen,
    InferencePrescreen,
    PrescreenRegistry,
    PrescreenVerdict,
    combine_verdicts,
)


def _submit(pipeline, **overrides):
    fields = {"name": "New Chain", "corporate_tin": "111-222-333"}
    fields.update(overrides)
    built = contribution_for_correction("corporation", None, fields, contributor="worker")
    return pipeline.queue.submit(built.contribution).contribution


def test_merge_without_prescreen_is_refused(pipeline):
    contribution = _submit(pipeline)
    pipeline.queue.review(contribution.contribution_id, reviewer="staff-1", approved=True)
    result = pipeline.queue.merge(contribution.contribution_id)
    assert result.error is not None
    assert result.error.code == LearningErrorCode.PRESCREEN_REQUIRED


def test_review_without_prescreen_is_refused(pipeline):
    contribution = _submit(pipeline)
    result = pipeline.queue.review(contribution.contribution_id, reviewer="staff-1", approved=True)
    assert result.error is not None
    assert result.error.code == LearningErrorCode.PRESCREEN_REQUIRED


def test_full_path_prescreen_then_approval_then_merge(pipeline):
    contribution = _submit(pipeline)
    assert asyncio.run(pipeline.queue.prescreen(contribution.contribution_id)).ok
    assert pipeline.queue.review(contribution.contribution_id, "staff-1", True).ok
    merged = pipeline.queue.merge(contribution.contribution_id)
    assert merged.ok and merged.contribution.merged
    assert len(pipeline.entities.store.all_of("corporation")) == 1


def test_merging_twice_is_refused(pipeline):
    contribution = _submit(pipeline)
    asyncio.run(pipeline.queue.prescreen(contribution.contribution_id))
    pipeline.queue.review(contribution.contribution_id, "staff-1", True)
    pipeline.queue.merge(contribution.contribution_id)
    again = pipeline.queue.merge(contribution.contribution_id)
    assert again.error is not None and again.error.code == LearningErrorCode.ALREADY_MERGED
    assert len(pipeline.entities.store.all_of("corporation")) == 1


def test_reviewing_twice_is_refused(pipeline):
    contribution = _submit(pipeline)
    asyncio.run(pipeline.queue.prescreen(contribution.contribution_id))
    pipeline.queue.review(contribution.contribution_id, "staff-1", True)
    again = pipeline.queue.review(contribution.contribution_id, "staff-2", False)
    assert again.error is not None and again.error.code == LearningErrorCode.ALREADY_REVIEWED


def test_heuristic_prescreen_rejects_a_malformed_submission(pipeline):
    contribution = _submit(pipeline, corporate_tin="")
    screened = asyncio.run(pipeline.queue.prescreen(contribution.contribution_id))
    assert screened.contribution.staff_review_status == "rejected"
    assert screened.contribution.llm_prescreen_verdict == "malformed"
    refused = pipeline.queue.merge(contribution.contribution_id)
    assert refused.error is not None
    assert refused.error.code == LearningErrorCode.APPROVAL_REQUIRED


def test_unavailable_prescreen_keeps_a_contribution_pending_and_unmerged(
    pipeline_without_prescreen,
):
    """Degrading gracefully means review takes longer — never that it was skipped."""
    pipeline = pipeline_without_prescreen
    contribution = _submit(pipeline)
    screened = asyncio.run(pipeline.queue.prescreen(contribution.contribution_id))
    assert screened.error is not None
    assert screened.error.code == LearningErrorCode.PRESCREEN_UNAVAILABLE
    assert screened.contribution.staff_review_status == "pending"
    assert not pipeline.queue.merge(contribution.contribution_id).ok


def test_unknown_contribution_is_data_not_an_exception(pipeline):
    for call in (
        lambda: pipeline.queue.get("nope"),
        lambda: pipeline.queue.review("nope", "staff-1", True),
        lambda: pipeline.queue.merge("nope"),
        lambda: asyncio.run(pipeline.queue.prescreen("nope")),
    ):
        result = call()
        assert result.error is not None
        assert result.error.code == LearningErrorCode.UNKNOWN_CONTRIBUTION


def test_combined_verdict_treats_any_rejection_as_decisive():
    verdicts = (
        PrescreenVerdict("a", True, "clean"),
        PrescreenVerdict("b", False, "duplicate", "seen before"),
    )
    combined = combine_verdicts(verdicts)
    assert not combined.passed and combined.verdict == "duplicate"


def test_combined_verdict_of_all_unavailable_is_not_a_pass():
    verdicts = (PrescreenVerdict("a", False, "unavailable", available=False),)
    combined = combine_verdicts(verdicts)
    assert not combined.passed and not combined.available


def test_inference_prescreen_without_a_dispatcher_reports_unavailable():
    verdict = asyncio.run(
        InferencePrescreen().prescreen(
            contribution_for_correction(
                "corporation", None, {"name": "x", "corporate_tin": "y"}, "worker"
            ).contribution
        )
    )
    assert not verdict.available


def test_both_providers_run_when_both_are_registered():
    registry = PrescreenRegistry((HeuristicPrescreen(), InferencePrescreen()))
    assert registry.names() == ("heuristic", "inference")


def test_proposed_change_stays_a_frozen_mapping_through_the_queue(pipeline):
    """A queued change is read by prescreen and again by a human; nothing may edit it."""
    contribution = _submit(pipeline)
    assert isinstance(contribution.proposed_change, FrozenDict)


# ------------------------------------------------------- regressions found in review


def test_an_unavailable_prescreen_does_not_satisfy_the_prescreen_gate(
    pipeline_without_prescreen,
):
    """The gate that was claimed must be the gate that actually fires.

    Recording the string "unavailable" as the prescreen verdict made
    `Contribution.prescreened` true, so `merge`'s own prescreen gate passed on a
    contribution nothing had ever screened. On the user path the approval gate happened to
    catch it; on the staff direct-to-global path (`staff_review_status="not_applicable"`)
    there is no approval gate behind it, and the contribution merged into `GLOBAL`.
    """
    pipeline = pipeline_without_prescreen
    contribution = _submit(pipeline)
    asyncio.run(pipeline.queue.prescreen(contribution.contribution_id))
    stored = pipeline.queue.get(contribution.contribution_id).contribution
    assert stored.llm_prescreen_verdict is None
    assert not stored.prescreened
    refused = pipeline.queue.merge(contribution.contribution_id)
    assert refused.error is not None
    assert refused.error.code == LearningErrorCode.PRESCREEN_REQUIRED


def test_the_staff_path_cannot_merge_when_prescreen_is_unavailable(
    pipeline_without_prescreen,
):
    """The staff path is a shorter path, not one with no gates left."""
    pipeline = pipeline_without_prescreen
    result = asyncio.run(
        pipeline.layering.staff_create_global(
            "corporation", {"name": "Ghost Chain", "corporate_tin": "1"}, staff_user_id="s1"
        )
    )
    assert result.error is not None
    assert result.error.code == LearningErrorCode.PRESCREEN_UNAVAILABLE
    forced = pipeline.queue.merge(result.contribution.contribution_id)
    assert forced.error is not None
    assert forced.error.code == LearningErrorCode.PRESCREEN_REQUIRED
    assert pipeline.entities.store.all_of("corporation") == ()


def test_an_unavailable_prescreen_is_still_recorded_in_the_audit_mirror(
    pipeline_without_prescreen,
):
    """Not merging is not the same as leaving no trace of the attempt."""
    pipeline = pipeline_without_prescreen
    contribution = _submit(pipeline)
    asyncio.run(pipeline.queue.prescreen(contribution.contribution_id))
    events = pipeline.queue.mirror.for_contribution(contribution.contribution_id)
    assert [e.event for e in events] == ["submitted", "prescreened"]
    assert events[-1].detail["verdict"] == "unavailable"


def test_a_heuristic_screen_given_an_empty_required_map_screens_nothing(pipeline):
    """`is None`, not truthiness — an empty mapping is a real instruction, not a default."""
    screen = HeuristicPrescreen(required_fields=FrozenDict({}))
    contribution = _submit(pipeline, corporate_tin="")
    verdict = asyncio.run(screen.prescreen(contribution))
    assert verdict.passed

"""The review-decision trail (`v3-deepdive-40-temporal-learning.md` §6).

Append-only has to be a property of the public surface, not a convention
(`docs/PRINCIPLES.md` §2.3) — an audit trail's whole value is being trustworthy in exactly
the scenario where someone would like to quietly alter it. The first test asserts the
absence of the methods that would allow that, which is the guarantee itself.

This module is also where the deliberate deviation from §6 is recorded: the git-tracked
mirror that section describes was scoped and reversed (`docs/MAINTENANCE.md` §4), so the
trail is a plain append-only record with a diffable rendering rather than a git repository.
"""

from __future__ import annotations

import asyncio

from core.architect.temporal_learning.audit_mirror import ReviewAuditMirror


def test_the_mirror_exposes_no_way_to_change_what_it_recorded():
    mirror = ReviewAuditMirror()
    for forbidden in ("update", "delete", "edit", "remove", "clear", "amend"):
        assert not hasattr(mirror, forbidden)


def test_entries_handed_out_cannot_be_used_to_mutate_the_trail():
    mirror = ReviewAuditMirror()
    entries = mirror.entries()
    assert isinstance(entries, tuple)


def test_a_rejection_is_recorded_as_fully_as_an_approval(pipeline):
    from core.architect.temporal_learning.contribution import contribution_for_correction

    built = contribution_for_correction(
        "corporation", None, {"name": "Rejected Co", "corporate_tin": "1"}, "human:user-1"
    ).contribution
    pipeline.queue.submit(built)
    asyncio.run(pipeline.queue.prescreen(built.contribution_id))
    pipeline.queue.review(built.contribution_id, "staff-1", approved=False, reason="bad TIN")

    trail = pipeline.queue.mirror.for_contribution(built.contribution_id)
    events = [e.event for e in trail]
    assert events == ["submitted", "prescreened", "decided"]
    decision = trail[-1]
    assert decision.actor == "human:staff-1"
    assert decision.detail["approved"] is False
    assert decision.detail["reason"] == "bad TIN"


def test_render_is_stable_and_only_grows(pipeline):
    from core.architect.temporal_learning.contribution import contribution_for_correction

    built = contribution_for_correction(
        "corporation", None, {"name": "Co", "corporate_tin": "1"}, "human:user-1"
    ).contribution
    pipeline.queue.submit(built)
    first = pipeline.queue.mirror.render()

    asyncio.run(pipeline.queue.prescreen(built.contribution_id))
    second = pipeline.queue.mirror.render()

    assert second.startswith(first)
    assert "event: prescreened" in second

"""Curate — the self-cleaning pass (`v3-deepdive-40-temporal-learning.md` §7).

**The load-bearing property: Curate never deletes or merges anything.** Every candidate it
finds is staged through the same moderation pipeline a new contribution goes through. Self
-cleaning gets no shortcut around the review gate for being "only cleanup" — a wrongly
merged vendor or a wrongly pruned entry is a smaller version of the same mistake an
unreviewed bad contribution would be, and `docs/PRINCIPLES.md` §4.3 applies identically.
`propose_all` returns contributions; nothing in this module can write to an entity table.

Three distinct patterns, not one generic cleanup job, because each fails differently:
`low_confidence_stale` prunes, `near_duplicate_merge` combines, `abandoned_pending_review`
only surfaces.

**Similarity is Matching's, not ours.** §9 is explicit that the near-duplicate case reuses
Matching's own fuzzy scoring rather than reimplementing it, so this module takes a scorer
through one seam (`docs/PRINCIPLES.md` §1.3) and falls back to exact-on-normalized-name
comparison when none is supplied — a real, conservative check that adds no dependency and
never claims to be fuzzy matching.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from ..vendor_directory.aliases import normalize_vendor_name
from .contracts import (
    Contribution,
    Corporation,
    CurationCandidate,
    CurationListResult,
    Entity,
    VendorLayer,
    utcnow,
)
from .contribution import contribution_from_curation
from .entities import EntityManager, entity_id_of, entity_type_of
from .moderation_queue import ModerationQueue

#: Resolved in the deep-dive's §12: the same 14-day convenience window Support Ticketing
#: applies to its own stale-resolved tickets. One number for the same underlying "has this
#: sat untouched long enough to be worth surfacing" judgement, rather than a second value
#: invented for a structurally identical question.
ABANDONED_REVIEW_DAYS = 14

#: Neither of these two is settled anywhere in the corpus. Both are reasoned defaults for
#: "very few confirming observations" and "hasn't been touched in a long time", chosen to
#: be conservative — Curate only ever *proposes*, so an over-eager threshold costs a
#: reviewer's attention, while an over-cautious one costs nothing but clutter. Treated as
#: provisional until the bench suite says otherwise (`docs/PRINCIPLES.md` §5).
STALE_LOCAL_DAYS = 180
STALE_MAX_OBSERVATIONS = 1

#: A scorer takes two normalized names and returns 0.0-1.0. Matching supplies the real one.
SimilarityScorer = Callable[[str, str], float]

#: Above this, two entries are proposed as near-duplicates. Provisional, same as above.
NEAR_DUPLICATE_THRESHOLD = 0.92


def _exact_normalized_scorer(left: str, right: str) -> float:
    """The dependency-free fallback: normalized equality, nothing fuzzy about it."""
    return 1.0 if left == right and left else 0.0


def find_low_confidence_stale(
    entities: Iterable[Entity],
    observation_counts: Mapping[str, int],
    now=None,
    stale_days: int = STALE_LOCAL_DAYS,
    max_observations: int = STALE_MAX_OBSERVATIONS,
) -> tuple[CurationCandidate, ...]:
    """`LOCAL` entries with very few confirming observations and no recent activity.

    Scoped to `LOCAL` deliberately: a `GLOBAL` entry passed human review, and quietly
    proposing to prune what a reviewer approved is a different and much less welcome
    action than tidying an unshared local guess that never accumulated evidence.
    """
    reference = now or utcnow()
    cutoff = reference.timestamp() - stale_days * 86400
    out: list[CurationCandidate] = []
    for entity in entities:
        if entity.layer is not VendorLayer.LOCAL or entity.shared:
            continue
        entity_id = entity_id_of(entity)
        if observation_counts.get(entity_id, 0) > max_observations:
            continue
        if entity.created_at.timestamp() >= cutoff:
            continue
        out.append(
            CurationCandidate(
                candidate_type="low_confidence_stale",
                target_entries=(entity_id,),
                reasoning=(
                    f"local, unshared, {observation_counts.get(entity_id, 0)} confirming "
                    f"observation(s), untouched for over {stale_days} days"
                ),
                # `entity_type_of`, not a two-way isinstance: a `Franchiser` passed here was
                # previously labelled "branch", which would send a reviewer — and any merge
                # acting on the candidate — at the wrong table entirely.
                entity_type=entity_type_of(entity),
            )
        )
    return tuple(out)


def find_near_duplicates(
    entities: Iterable[Entity],
    scorer: SimilarityScorer | None = None,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> tuple[CurationCandidate, ...]:
    """Corporations similar enough that they were probably meant to be one entry.

    Compares normalized names, so the trivial "Inc." / "Incorporated" split is caught with
    no scorer at all; a real scorer from Matching catches the spelling variants that are
    the actual point of this candidate type.
    """
    score = scorer or _exact_normalized_scorer
    corporations = [e for e in entities if isinstance(e, Corporation)]
    normalized = {c.corporation_id: normalize_vendor_name(c.name) for c in corporations}
    out: list[CurationCandidate] = []
    for i, left in enumerate(corporations):
        for right in corporations[i + 1:]:
            if left.layer is not right.layer:
                continue
            value = score(normalized[left.corporation_id], normalized[right.corporation_id])
            if value < threshold:
                continue
            pair = tuple(sorted((left.corporation_id, right.corporation_id)))
            out.append(
                CurationCandidate(
                    candidate_type="near_duplicate_merge",
                    target_entries=pair,
                    reasoning=(
                        f"{left.name!r} and {right.name!r} score {value:.2f} on normalized "
                        f"name similarity and were never reconciled into one entry"
                    ),
                )
            )
    return tuple(out)


def find_abandoned_reviews(
    queue: ModerationQueue, days: int = ABANDONED_REVIEW_DAYS
) -> tuple[CurationCandidate, ...]:
    """Contributions that have sat `pending` past the review turnaround window.

    Surfaced, never auto-decided. An aging contribution is a signal about the review
    process, and auto-approving or auto-rejecting it would be the system deciding a
    question a human declined to answer.
    """
    return tuple(
        CurationCandidate(
            candidate_type="abandoned_pending_review",
            target_entries=(c.contribution_id,),
            reasoning=f"pending staff review for more than {days} days",
            entity_type=c.target_entity_type,
        )
        for c in queue.pending_longer_than(days)
    )


class Curator:
    """The idle-time job: scan, then stage every candidate through the review pipeline.

    Registered as a Background Workers idle-time job. Holds the queue so `propose_all` can
    stage what it finds — and holds `EntityManager` read-only, since applying a candidate
    is the merge step's job, not this class's.
    """

    def __init__(
        self,
        entities: EntityManager,
        queue: ModerationQueue,
        scorer: SimilarityScorer | None = None,
    ) -> None:
        self._entities = entities
        self._queue = queue
        self._scorer = scorer

    def scan(self, observation_counts: Mapping[str, int] | None = None) -> CurationListResult:
        """Every candidate of every type, in one pass. Read-only."""
        counts = observation_counts or {}
        corporations = self._entities.store.all_of("corporation")
        branches = self._entities.store.all_of("branch")
        candidates = (
            find_low_confidence_stale(tuple(corporations) + tuple(branches), counts)
            + find_near_duplicates(corporations, self._scorer)
            + find_abandoned_reviews(self._queue)
        )
        return CurationListResult(candidates=candidates)

    def propose_all(
        self, observation_counts: Mapping[str, int] | None = None
    ) -> tuple[Contribution, ...]:
        """Stage every candidate as an ordinary contribution.

        This is the whole of Curate's write surface, and it writes to the *queue* — never
        to an entity. A candidate becomes real only if a human approves it (§7).
        """
        found = self.scan(observation_counts)
        staged: list[Contribution] = []
        for candidate in found.candidates:
            result = self._queue.submit(contribution_from_curation(candidate))
            if result.contribution is not None:
                staged.append(result.contribution)
        return tuple(staged)


__all__ = [
    "ABANDONED_REVIEW_DAYS",
    "NEAR_DUPLICATE_THRESHOLD",
    "STALE_LOCAL_DAYS",
    "STALE_MAX_OBSERVATIONS",
    "Curator",
    "SimilarityScorer",
    "find_abandoned_reviews",
    "find_low_confidence_stale",
    "find_near_duplicates",
]

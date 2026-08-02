"""Building contributions — the staged-write unit (`v3-deepdive-40-temporal-learning.md` §4).

A `Contribution` is a *proposal*, and everything in this module produces one without
applying anything. That split is the point: the only code that writes to the `GLOBAL`
layer is `EntityManager.apply_contribution`, reached only from the moderation queue's
merge step, so there is no function anywhere that both constructs a change and lands it.

Three ways a contribution comes into existence, and they are genuinely different:

- **A user shares a `LOCAL` entity** (§3.1) — proposes a *new* global entity, so
  `target_entity_id` is `None` and the local entity's id rides along in
  `proposed_change["source_entity_id"]` for traceability. Full pipeline: prescreen, then
  staff review.
- **Staff writes directly to global** (§3.2) — prescreen only, `staff_review_status` set
  to `"not_applicable"` because the actor's own role already carries the authority a
  second staff member's approval would supply.
- **Curate proposes a cleanup** (§7) — same pipeline as any other contribution, carrying
  `curation_type` so a reviewer can see what kind of cleanup they are being asked about.

`proposed_change` is always a `FrozenDict` (`docs/PRINCIPLES.md` §2.1). It sits in a queue
for as long as review takes, is read by the prescreen step and again by a human, and a
plain dict there would be mutable by every one of them.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from common.frozen_dict import FrozenDict

from .contracts import (
    Contribution,
    ContributionResult,
    CurationCandidate,
    Entity,
    EntityType,
    LearningError,
    VendorLayer,
)
from .entities import entity_id_of, entity_type_of
from .errors import LearningErrorCode, learning_message_for

#: Fields that describe *where* an entity sits rather than *what it is*. Excluded from a
#: snapshot because a contribution proposes facts, never its own placement or ownership.
_NON_FACT_FIELDS = frozenset(
    {"layer", "shared", "owner_user_id", "created_at",
     "corporation_id", "branch_id", "franchiser_id"}
)


def _error(code: str, detail: str = "") -> LearningError:
    return LearningError(code=code, detail=detail or learning_message_for(code))


def new_contribution_id() -> str:
    return f"contrib-{uuid.uuid4().hex[:12]}"


def snapshot_of(entity: Entity) -> FrozenDict:
    """The proposable facts of an entity, as a `FrozenDict`.

    `Branch.corporation_id` and `Branch.franchiser_id` are deliberately kept — they are
    the whole content of a branch record and the references §4 exists to preserve — while
    the entity's *own* id is dropped, since a merge mints a new global id rather than
    carrying a local one across.
    """
    kept = {
        name: getattr(entity, name)
        for name in entity.__dataclass_fields__  # type: ignore[attr-defined]
        if name not in _NON_FACT_FIELDS
    }
    if entity_type_of(entity) == "branch":
        # A branch's references *are* its content — they are excluded above only because
        # the same field names are an entity's own id on the other two types.
        kept["corporation_id"] = entity.corporation_id
        kept["franchiser_id"] = entity.franchiser_id
    return FrozenDict(kept)


def contribution_from_entity(
    entity: Entity, contributor: str, staff_authored: bool = False
) -> Contribution:
    """Package a `LOCAL` entity as a proposed new `GLOBAL` entity.

    Only ever called from `layering.share_entity`, after the consent gate. Nothing else in
    this package calls it, and nothing should: constructing this object is what "eligible
    for global review" means, and it must not be reachable without that gate.
    """
    change = dict(snapshot_of(entity))
    change["source_entity_id"] = entity_id_of(entity)
    return Contribution(
        contribution_id=new_contribution_id(),
        contributor=contributor,
        target_entity_type=entity_type_of(entity),
        target_entity_id=None,
        proposed_change=FrozenDict(change),
        target_layer=VendorLayer.GLOBAL,
        staff_review_status="not_applicable" if staff_authored else "pending",
    )


def contribution_for_correction(
    entity_type: EntityType,
    entity_id: str | None,
    change: Mapping[str, object],
    contributor: str,
    staff_authored: bool = False,
) -> ContributionResult:
    """A proposed correction to (or creation of) a `GLOBAL` entity.

    Errors are returned, never raised: an empty or non-mapping change is a caller mistake
    that belongs in `result.error`, not an exception the gRPC layer would have to catch.
    """
    # `Mapping`, never `dict` — a FrozenDict handed in by a caller is not a dict subclass
    # on 3.15+, and this check silently taking the wrong branch is exactly the failure
    # `docs/PRINCIPLES.md` §2.1 warns about.
    if not isinstance(change, Mapping) or not change:
        return ContributionResult(
            error=_error(LearningErrorCode.INVALID_CHANGE, "change is empty or not a mapping")
        )
    return ContributionResult(
        contribution=Contribution(
            contribution_id=new_contribution_id(),
            contributor=contributor,
            target_entity_type=entity_type,
            target_entity_id=entity_id,
            proposed_change=FrozenDict(dict(change)),
            target_layer=VendorLayer.GLOBAL,
            staff_review_status="not_applicable" if staff_authored else "pending",
        )
    )


def contribution_from_curation(
    candidate: CurationCandidate, contributor: str = "worker"
) -> Contribution:
    """Stage a cleanup proposal as an ordinary contribution.

    Curate gets no shortcut around the review gate (§7). A wrongly-merged vendor or a
    wrongly-pruned entry is a smaller version of the same mistake an unreviewed bad
    contribution would be, and `docs/PRINCIPLES.md` §4.3 applies identically — which is
    why this returns the same type the user-share path does, with `staff_review_status`
    left `"pending"` even though the proposer is the system itself.
    """
    return Contribution(
        contribution_id=new_contribution_id(),
        contributor=contributor,
        target_entity_type=candidate.entity_type,
        target_entity_id=candidate.target_entries[0] if candidate.target_entries else None,
        proposed_change=FrozenDict(
            {
                "candidate_type": candidate.candidate_type,
                "target_entries": candidate.target_entries,
                "reasoning": candidate.reasoning,
            }
        ),
        target_layer=VendorLayer.GLOBAL,
        staff_review_status="pending",
        curation_type=candidate.candidate_type,
    )


def merge_payload(contribution: Contribution) -> dict[str, object]:
    """The fields a merge should actually write, with bookkeeping keys stripped.

    `source_entity_id` and the curation keys exist for traceability and review, and are
    not facts about the entity — writing them onto the record would quietly invent fields
    the contracts do not have.
    """
    return {
        k: v
        for k, v in contribution.proposed_change.items()
        if k not in {"source_entity_id", "candidate_type", "target_entries", "reasoning"}
    }


__all__ = [
    "contribution_for_correction",
    "contribution_from_curation",
    "contribution_from_entity",
    "merge_payload",
    "new_contribution_id",
    "snapshot_of",
]

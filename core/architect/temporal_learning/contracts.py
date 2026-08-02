"""temporal_learning data contracts (`v3-deepdive-40-temporal-learning.md` §3-§7).

The three-entity model here is not a modelling preference, it is a Philippine business
fact: a local franchise operator often puts *their own* corporation's name and TIN on a
receipt alongside or instead of the parent franchise corporation's. `Corporation`
(the franchise entity and its TIN) and `Franchiser` (the local operator's own corporation
and TIN) are therefore separate standalone entities, and `Branch` — one physical location,
one address — references both by id rather than embedding either. Flattening this back
into "franchiser fields on the branch row" reintroduces the exact problem §4 exists to
fix: one franchiser operating branches under two different corporations would have their
name and TIN duplicated per branch, with no structural guarantee the duplicates are ever
recognised as the same franchiser.

Every type is `@dataclass(frozen=True)`; `proposed_change` and `default_value` are
`FrozenDict`, never plain dicts (`docs/PRINCIPLES.md` §2.1). Errors are data: results
carry `error: LearningError | None`, never an exception across the boundary (§4.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    """Timezone-aware UTC. Naive datetimes are never written into a contract here."""
    return datetime.now(timezone.utc)


class VendorLayer(str, Enum):
    """Where a fact is visible (§3).

    `LOCAL` is written freely with no review of any kind — a private fact cannot hurt
    anyone but the user who created it, which is what makes it the "safe to self-apply"
    gate Tool Call API's own mutating tools rely on. `GLOBAL` is the shared directory
    every user and instance sees, and nothing reaches it without passing §6's pipeline.
    """

    LOCAL = "local"
    GLOBAL = "global"


#: The three learnable entity types. Anything not in this tuple is not a thing this
#: sub-API knows how to learn — the taxonomy of what *can* be contributed belongs to
#: Architect's registry, never to this sub-API (`v3-deepdive-40` §1).
EntityType = Literal["corporation", "branch", "franchiser"]

#: Review state of a contribution. `not_applicable` is staff's own direct-to-global
#: path (§3.2), where the actor's role already carries the authority a second staff
#: member's approval would otherwise supply.
ReviewStatus = Literal["not_applicable", "pending", "approved", "rejected"]

#: What Curate is allowed to propose (§7). Deliberately three named patterns rather than
#: one generic "clean things up" job, because each one has a different failure mode when
#: it gets applied wrongly.
CurationType = Literal[
    "low_confidence_stale", "near_duplicate_merge", "abandoned_pending_review"
]


@dataclass(frozen=True)
class Corporation:
    """The overall franchise/parent entity — e.g. a fast-food chain's PH corporation,
    distinct from any one physical location."""

    corporation_id: str
    name: str
    corporate_tin: str
    layer: VendorLayer = VendorLayer.LOCAL
    shared: bool = False
    owner_user_id: str | None = None
    category_code: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Franchiser:
    """A standalone entity, deliberately NOT embedded per-branch.

    One franchiser can operate branches under multiple different corporations; embedding
    their name and TIN on every `Branch` would duplicate the same facts across every
    branch they run, so a TIN correction would have to be applied once per branch and
    nothing would guarantee the copies stayed in agreement (§4).
    """

    franchiser_id: str
    name: str
    franchiser_tin: str
    layer: VendorLayer = VendorLayer.LOCAL
    shared: bool = False
    owner_user_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Branch:
    """One physical location: exactly one `Corporation`, optionally one `Franchiser`.

    `franchiser_id is None` is a legitimate, permanent end state, not "not filled in yet"
    — plenty of real branches are corporate-owned with no local operator at all
    (§12, resolved).
    """

    branch_id: str
    corporation_id: str
    address: str
    franchiser_id: str | None = None
    layer: VendorLayer = VendorLayer.LOCAL
    shared: bool = False
    owner_user_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)


#: Union of the three, for stores and callers that handle any entity uniformly.
Entity = Corporation | Franchiser | Branch


@dataclass(frozen=True)
class Contribution:
    """A proposed addition or correction, staged through §6's pipeline.

    `target_entity_id is None` means a genuinely new entity; a value means a correction
    to an existing one. `proposed_change` is a `FrozenDict` because it crosses a process
    boundary and is retained in the queue for as long as review takes.
    """

    contribution_id: str
    contributor: str
    target_entity_type: EntityType
    target_entity_id: str | None
    proposed_change: FrozenDict
    target_layer: VendorLayer = VendorLayer.GLOBAL
    llm_prescreen_verdict: str | None = None
    staff_review_status: ReviewStatus = "pending"
    merged: bool = False
    submitted_at: datetime = field(default_factory=utcnow)
    curation_type: CurationType | None = None

    @property
    def prescreened(self) -> bool:
        return self.llm_prescreen_verdict is not None


@dataclass(frozen=True)
class ReviewDecision:
    """One staff approve/reject, recorded whether or not it changed anything.

    Kept as its own contract rather than folded into `Contribution` because the review
    *process* is what the audit mirror (§6) records, and a decision has an actor and a
    reason the contribution itself does not carry.
    """

    contribution_id: str
    reviewer: str
    approved: bool
    reason: str = ""
    decided_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class CategoryDefault:
    """A learned, evolving category-level fallback (§5).

    Always a fallback: any actual vendor-specific fact wins over this, however high
    `confidence` has climbed. `confidence` is derived from how many confirmed `GLOBAL`
    vendors in the category actually agree with the value, not asserted.
    """

    category: str
    field_name: str
    default_value: FrozenDict
    confidence: float = 0.0
    sample_size: int = 0


@dataclass(frozen=True)
class CurationCandidate:
    """A proposed cleanup. Never applied directly — staged through §6 like anything else."""

    candidate_type: CurationType
    target_entries: tuple[str, ...]
    reasoning: str
    entity_type: EntityType = "corporation"


@dataclass(frozen=True)
class LearningError:
    """An error as data. Maps onto the `error_code`/`error_detail` proto pair."""

    code: str
    detail: str = ""


@dataclass(frozen=True)
class EntityResult:
    entity: Entity | None = None
    error: LearningError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ContributionResult:
    contribution: Contribution | None = None
    error: LearningError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ListEntitiesResult:
    entities: tuple[Entity, ...] = ()
    error: LearningError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class CategoryDefaultsResult:
    defaults: tuple[CategoryDefault, ...] = ()
    error: LearningError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class CurationListResult:
    candidates: tuple[CurationCandidate, ...] = ()
    error: LearningError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


__all__ = [
    "Branch",
    "CategoryDefault",
    "CategoryDefaultsResult",
    "Contribution",
    "ContributionResult",
    "Corporation",
    "CurationCandidate",
    "CurationListResult",
    "CurationType",
    "Entity",
    "EntityResult",
    "EntityType",
    "Franchiser",
    "LearningError",
    "ListEntitiesResult",
    "ReviewDecision",
    "ReviewStatus",
    "VendorLayer",
    "utcnow",
]

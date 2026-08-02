"""Local/global layering and the sharing gate (`v3-deepdive-40-temporal-learning.md` §3).

**The gate this file exists for**: a `LOCAL` fact does not enter the moderation queue just
because it exists. An explicit share action must happen first, and it is never triggered
by the learning pipeline on its own. This was a genuine gap in the first version of §3 —
that version implied any local contribution could be silently swept toward global review —
and the reason it matters goes beyond caution: a user's local corrections can carry details
specific to their own situation (an internal note, a locally-relevant alias) that were
never meant to become everyone's shared truth.

There is no standing "always share automatically" preference, and there should not be
(§12, resolved). A toggle that shares everything would quietly erode the entire point of a
consent gate; the explicit, per-entity nature of the action is what makes it mean anything.

**Staff's direct-to-global path is genuinely different, not an exemption.** It skips the
*user's local layer*, not the review pipeline: the contribution still prescreens, and it
still lands a fully recorded audit event with a `human:<staff_user_id>` actor. What it
skips is a second staff member approving the first one's own submission, which would be a
circular gate rather than a safety check.
"""

from __future__ import annotations

from collections.abc import Mapping

from .contracts import (
    ContributionResult,
    Entity,
    EntityType,
    LearningError,
    ListEntitiesResult,
    VendorLayer,
)
from .contribution import contribution_for_correction, contribution_from_entity
from .entities import EntityManager
from .errors import LearningErrorCode, SharingGateViolation, learning_message_for
from .moderation_queue import ModerationQueue


def _error(code: str, detail: str = "") -> LearningError:
    return LearningError(code=code, detail=detail or learning_message_for(code))


def visible_to(entity: Entity, user_id: str | None) -> bool:
    """Whether a user may see an entity at all.

    `GLOBAL` is everyone's; `LOCAL` is its owner's alone. Anonymous callers see only the
    global layer — an unauthenticated read must never surface a private fact.
    """
    if entity.layer is VendorLayer.GLOBAL:
        return True
    return user_id is not None and entity.owner_user_id == user_id


class LayeringService:
    """The only route from `LOCAL` toward `GLOBAL`.

    Deliberately holds both the entity manager and the queue: the consent gate is the
    handoff between them, and splitting it across two objects would leave a path where
    something could submit a contribution for an entity that was never shared.
    """

    def __init__(self, entities: EntityManager, queue: ModerationQueue) -> None:
        self._entities = entities
        self._queue = queue

    async def share_entity(
        self, entity_type: EntityType, entity_id: str, requesting_user_id: str
    ) -> ContributionResult:
        """§3.1's explicit consent step. The *only* thing that makes a local fact eligible.

        Refuses, rather than no-ops, in every case where it cannot honestly say consent was
        given for this entity by this user right now — an unknown entity, someone else's
        entity, an already-global one, or one already shared.
        """
        found = self._entities.get(entity_type, entity_id)
        if found.error is not None or found.entity is None:
            return ContributionResult(error=found.error)
        entity = found.entity
        if entity.layer is VendorLayer.GLOBAL:
            return ContributionResult(error=_error(LearningErrorCode.ALREADY_GLOBAL, entity_id))
        if entity.owner_user_id != requesting_user_id:
            return ContributionResult(
                error=_error(LearningErrorCode.UNKNOWN_ENTITY,
                             "not visible to the requesting user")
            )
        if entity.shared:
            return ContributionResult(error=_error(LearningErrorCode.ALREADY_SHARED, entity_id))

        shared_entity = self._entities.mark_shared(entity)
        contribution = contribution_from_entity(
            shared_entity, contributor=f"human:{requesting_user_id}"
        )
        return self._queue.submit(contribution)

    def assert_shared(self, entity: Entity) -> None:
        """Internal guard for any future code path that stages a local entity.

        Raises rather than returning a result on purpose: this is not a caller-facing
        outcome, it is a bug catcher for a path that should not exist. If it ever fires,
        something has found a way around `share_entity`, and failing loudly is the point
        (`docs/PRINCIPLES.md` §4.3 — never silently override a genuine gate).
        """
        if entity.layer is VendorLayer.LOCAL and not entity.shared:
            raise SharingGateViolation(
                f"{entity!r} has not been shared; a local fact never enters the queue on its own"
            )

    async def staff_create_global(
        self, entity_type: EntityType, fields: Mapping[str, object], staff_user_id: str
    ) -> ContributionResult:
        """§3.2's direct path: prescreen, then merge. No second staff approval."""
        built = contribution_for_correction(
            entity_type, None, fields, contributor=f"human:{staff_user_id}", staff_authored=True
        )
        if built.error is not None or built.contribution is None:
            return built
        self._queue.submit(built.contribution)
        return await self._queue.process(built.contribution.contribution_id)

    async def staff_update_global(
        self,
        entity_type: EntityType,
        entity_id: str,
        change: Mapping[str, object],
        staff_user_id: str,
    ) -> ContributionResult:
        """A staff correction to an existing global entity — same shortened path as above.

        This is how a franchiser TIN correction is actually made: one update to the one
        `Franchiser` record, reflected by every branch that references it, never applied
        per-branch (§4).
        """
        existing = self._entities.get(entity_type, entity_id)
        if existing.error is not None:
            return ContributionResult(error=existing.error)
        built = contribution_for_correction(
            entity_type, entity_id, change,
            contributor=f"human:{staff_user_id}", staff_authored=True,
        )
        if built.error is not None or built.contribution is None:
            return built
        self._queue.submit(built.contribution)
        return await self._queue.process(built.contribution.contribution_id)

    def list_for_user(self, entity_type: EntityType, user_id: str | None) -> ListEntitiesResult:
        """§8's browse surface, with the visibility rule applied on read."""
        return self._entities.list_visible(entity_type, user_id)


__all__ = ["LayeringService", "visible_to"]

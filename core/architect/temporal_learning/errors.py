"""temporal_learning error codes and internal exception types.

Same two-layer split as the parent API's `errors.py`: stable codes that travel in a
`LearningError.code`, plus internal exceptions that never cross the boundary
(`docs/PRINCIPLES.md` §4.1).

Three of these codes exist specifically to make a refused shortcut legible rather than
silent. `NOT_SHARED`, `PRESCREEN_REQUIRED` and `APPROVAL_REQUIRED` are each returned by a
merge attempt that tried to skip a gate §3.1/§6 requires — the caller gets told exactly
which gate stopped it, because "nothing happened" would be indistinguishable from a bug.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class LearningErrorCode:
    """Stable, machine-readable codes. Values are never reused for a new meaning."""

    UNKNOWN_ENTITY = "unknown_entity"
    UNKNOWN_CONTRIBUTION = "unknown_contribution"
    UNKNOWN_ENTITY_TYPE = "unknown_entity_type"

    NOT_SHARED = "not_shared"
    ALREADY_SHARED = "already_shared"
    ALREADY_GLOBAL = "already_global"
    PRESCREEN_REQUIRED = "prescreen_required"
    APPROVAL_REQUIRED = "approval_required"
    ALREADY_REVIEWED = "already_reviewed"
    ALREADY_MERGED = "already_merged"

    STAFF_ROLE_REQUIRED = "staff_role_required"
    INVALID_REFERENCE = "invalid_reference"
    INVALID_CHANGE = "invalid_change"

    PRESCREEN_UNAVAILABLE = "prescreen_unavailable"


#: `FrozenDict` because it is a module-level constant read concurrently and never written
#: (`docs/PRINCIPLES.md` §2.1.1).
LEARNING_ERROR_MESSAGES = FrozenDict(
    {
        LearningErrorCode.UNKNOWN_ENTITY: "no such entity",
        LearningErrorCode.UNKNOWN_CONTRIBUTION: "no such contribution",
        LearningErrorCode.UNKNOWN_ENTITY_TYPE: "not a learnable entity type",
        LearningErrorCode.NOT_SHARED: "this entity has not been explicitly shared",
        LearningErrorCode.ALREADY_SHARED: "this entity has already been shared",
        LearningErrorCode.ALREADY_GLOBAL: "this entity is already in the global layer",
        LearningErrorCode.PRESCREEN_REQUIRED: "prescreen has not run on this contribution",
        LearningErrorCode.APPROVAL_REQUIRED: "staff approval has not been given",
        LearningErrorCode.ALREADY_REVIEWED: "this contribution has already been decided",
        LearningErrorCode.ALREADY_MERGED: "this contribution has already been merged",
        LearningErrorCode.STAFF_ROLE_REQUIRED: "only staff may take this path",
        LearningErrorCode.INVALID_REFERENCE: "a referenced entity does not exist",
        LearningErrorCode.INVALID_CHANGE: "the proposed change is empty or malformed",
        LearningErrorCode.PRESCREEN_UNAVAILABLE: "the prescreen provider is not available",
    }
)


def learning_message_for(code: str) -> str:
    return LEARNING_ERROR_MESSAGES.get(code, code)


class TemporalLearningError(Exception):
    """Base for everything this sub-package raises internally."""


class UnknownEntity(TemporalLearningError):
    """A referenced corporation/branch/franchiser does not exist in the caller's view."""


class SharingGateViolation(TemporalLearningError):
    """Something tried to move a `LOCAL` fact toward `GLOBAL` without an explicit share.

    This is the §3.1 consent gate. It is an internal exception rather than only a returned
    code because the queue must be able to refuse loudly on its own call path — a local
    fact silently swept into global review is the exact gap that section closed.
    """


class ReviewGateViolation(TemporalLearningError):
    """A merge was attempted without the prescreen and/or approval §6 requires."""


class PrescreenUnavailable(TemporalLearningError):
    """The Inference-backed prescreen could not run.

    Converted at the boundary into a contribution that stays pending, never into a merge.
    Degrading gracefully here means "review takes longer", never "review was skipped"
    (`docs/PRINCIPLES.md` §4.4 as bounded by §4.3).
    """


__all__ = [
    "LEARNING_ERROR_MESSAGES",
    "LearningErrorCode",
    "PrescreenUnavailable",
    "ReviewGateViolation",
    "SharingGateViolation",
    "TemporalLearningError",
    "UnknownEntity",
    "learning_message_for",
]

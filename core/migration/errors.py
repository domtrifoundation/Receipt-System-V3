"""Migration API error taxonomy.

Surfaced as `error_code`/`error_detail` on `MigrationResult` and `StepResult` rather than
raised across the boundary (`docs/PRINCIPLES.md` §4.1).

**This package fails closed harder than most, and deliberately.** Everywhere else in this
project §4.4's degrade-gracefully posture dominates: a missing OCR engine means that engine is
unavailable, a failing log sink degrades alone. Here, a missing migration step means the walk
**stops**, because the alternative is worse than not migrating at all. A structure left half
migrated — some steps applied, one skipped, later ones applied on top — is in a state no
version number describes and no step was written to expect. The whole value of a chained
registry (§1's "two different code paths could produce the same end state" argument) evaporates
the moment a gap is stepped over.

So `MissingMigrationStep` stops the walk, and `MigrationResult.reached_version` reports how far
it actually got. That number is the honest answer to "what state is this structure in now",
which matters more here than almost anywhere: a caller that assumed the target was reached
would then run code against a schema that does not exist.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class MigrationError(Exception):
    """Base for everything this API raises internally, never across its boundary."""


class MissingMigrationStep(MigrationError):
    """No registered step covers a bump the walk needs.

    Stops the walk rather than skipping the gap. §8 wants this caught in CI by the
    chain-integrity check precisely so it is never discovered here, mid-migration, on a live
    system — but if it ever is, stopping is the only safe response.
    """


class MultiVersionStep(MigrationError):
    """A registered step spanning more than one version bump (§1).

    Rejected at registration, not at run time. A shortcut step means two code paths can reach
    the same end state, and the two will disagree the moment one of them is edited — which is
    a correctness risk, not a performance trade.
    """


class DuplicateMigrationStep(MigrationError):
    """Two steps registered for the same bump.

    Which one runs would otherwise depend on import order, and a migration whose behaviour
    depends on import order is not reproducible — the one property a migration chain must have.
    """


class UnknownStructure(MigrationError):
    """A version query or migration naming a structure nothing has recorded a version for."""


class InvalidVersionRange(MigrationError):
    """A target below the current version, or a negative version.

    Downgrades are refused rather than attempted: this registry holds N→N+1 steps only, so
    walking backwards would require inverse steps nobody wrote, and guessing at one is how a
    "rollback" silently destroys data. Reverting is Persistence's own Historian-backed job
    (§1's boundary), not a direction this chain travels.
    """


class StepFailed(MigrationError):
    """A step's own `apply` raised.

    Converted to data at the runner boundary, never propagated: a batch migrating every user's
    database must not be taken down by one user's row that violated an assumption.
    """


ERROR_CODES: FrozenDict = FrozenDict(
    {
        MissingMigrationStep: "MISSING_MIGRATION_STEP",
        MultiVersionStep: "MULTI_VERSION_STEP",
        DuplicateMigrationStep: "DUPLICATE_MIGRATION_STEP",
        UnknownStructure: "UNKNOWN_STRUCTURE",
        InvalidVersionRange: "INVALID_VERSION_RANGE",
        StepFailed: "STEP_FAILED",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "MISSING_MIGRATION_STEP": (
            "No migration step exists for a required version bump; the walk stopped rather "
            "than skipping it."
        ),
        "MULTI_VERSION_STEP": "A migration step may only span one version bump.",
        "DUPLICATE_MIGRATION_STEP": "Two migration steps are registered for the same bump.",
        "UNKNOWN_STRUCTURE": "No schema version is recorded for that structure.",
        "INVALID_VERSION_RANGE": "The requested version range is not a forward walk.",
        "STEP_FAILED": "A migration step failed; the structure stopped at its last good version.",
        "INTERNAL": "An unmapped internal error.",
    }
)


def code_for(exc: BaseException) -> str:
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    return ERROR_SUMMARIES.get(code, ERROR_SUMMARIES["INTERNAL"])


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "DuplicateMigrationStep",
    "InvalidVersionRange",
    "MigrationError",
    "MissingMigrationStep",
    "MultiVersionStep",
    "StepFailed",
    "UnknownStructure",
    "code_for",
    "summary_for",
]

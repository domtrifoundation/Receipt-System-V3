"""Migration data contracts (`v3-deepdive-23-migration-api.md` §2, §3, §7).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). It is the only file in this
package that anything outside `core/migration/` imports from.

The load-bearing shape is that a step describes **exactly one version bump**. §1's boundary is
blunt about why: "N→N+2 is always N→N+1→N+2, chained, never a shortcut migration written to
skip a step, since that would mean two different code paths could produce the same end state, a
real correctness risk." So `MigrationStep` carries `from_version` and `to_version` rather than
a range, and the registry below can reject a step that spans more than one.

`MigrationOutcome` distinguishes `APPLIED` from `ALREADY_APPLIED`. §8's idempotency hook exists
because migrations get re-run after an interrupted batch, and a re-run that reported "applied"
would inflate any count derived from it and hide whether the batch actually did anything the
second time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StructureKind(str, Enum):
    """Which kind of persisted structure a version chain belongs to (§1).

    §1 names three: config, vendor/branch data, and the database schema. They are separate
    chains rather than one global version number because they evolve independently — a config
    key added in one release has nothing to do with the receipts table's own shape, and a
    single counter would force a migration step to exist for every bump of any of them.

    Values are stable wire strings. Adding a member is fine; renaming or reusing a value
    breaks anything that has persisted a version row.
    """

    DATABASE_SCHEMA = "database_schema"
    CONFIG = "config"
    VENDOR_DATA = "vendor_data"


class MigrationOutcome(str, Enum):
    """What one step's application produced.

    `ALREADY_APPLIED` is a success, not a failure — §8's idempotency hook is precisely about
    a re-run being "a safe no-op, not a duplicate application". Keeping it distinct from
    `APPLIED` is what lets an interrupted batch be re-run and still report honestly how much
    of it was genuinely new work.
    """

    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    FAILED = "failed"


@dataclass(frozen=True)
class SchemaVersion:
    """Where one structure currently sits in its own chain (§1)."""

    structure_id: str
    kind: StructureKind
    version: int
    updated_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class MigrationStep:
    """One N→N+1 bump — never a range (§3).

    `apply` is deliberately absent from this type: `contracts.py` holds no logic (§1.1), so the
    callable lives on `registry.RegisteredStep` alongside the step it belongs to. That split
    also means a step can be *described* — listed in a chain-integrity report, rendered in a
    release note — without importing the code that performs it.

    `description` is required rather than optional. A migration chain is read by whoever is
    diagnosing a half-migrated install months later, and a step identified only by its numbers
    tells them nothing about what changed.
    """

    kind: StructureKind
    from_version: int
    to_version: int
    description: str

    @property
    def is_single_bump(self) -> bool:
        """§1's chained-never-direct rule, as a checkable property of the step itself."""
        return self.to_version == self.from_version + 1


@dataclass(frozen=True)
class StepResult:
    """The outcome of applying one step to one structure."""

    step: MigrationStep
    structure_id: str
    outcome: MigrationOutcome
    started_at: datetime
    finished_at: datetime
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is not MigrationOutcome.FAILED


@dataclass(frozen=True)
class MigrationResult:
    """The outcome of walking one structure from its current version toward a target (§3, §7).

    Errors are data (`docs/PRINCIPLES.md` §4.1). A failed step stops the walk and the result
    carries how far it actually got — `reached_version` is the honest answer to "what state is
    this structure in now", which matters far more here than in most APIs: a caller that
    assumed the target was reached would then run code expecting a schema that does not exist.
    """

    structure_id: str
    kind: StructureKind
    from_version: int
    reached_version: int
    target_version: int
    steps: tuple[StepResult, ...] = ()
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code

    @property
    def complete(self) -> bool:
        return self.reached_version == self.target_version

    @property
    def applied_count(self) -> int:
        """Steps that did real work, excluding the ones that were already applied.

        Derived rather than stored so it cannot disagree with `steps` — and separate from
        `len(steps)` because §8's idempotency hook is about telling those two apart.
        """
        return sum(1 for s in self.steps if s.outcome is MigrationOutcome.APPLIED)


@dataclass(frozen=True)
class ChainIntegrityReport:
    """§8's chain-integrity hook, as a value rather than only a test assertion.

    "Confirms every registered version has exactly one N→N+1 step defined, no gaps — a missing
    step should fail CI, not be discovered mid-migration on a live system." Making it a real
    report rather than a bare boolean means the same check serves the test, a startup
    self-check, and an operator-facing status view without three implementations.
    """

    kind: StructureKind
    lowest_version: int
    highest_version: int
    missing_bumps: tuple[int, ...] = ()
    duplicate_bumps: tuple[int, ...] = ()
    multi_version_steps: tuple[str, ...] = ()

    @property
    def intact(self) -> bool:
        return not (self.missing_bumps or self.duplicate_bumps or self.multi_version_steps)


@dataclass(frozen=True)
class MigrationMetrics:
    """This API's own counters, snapshotted (`metrics.py`)."""

    migrations_attempted: int = 0
    steps_applied: int = 0
    steps_already_applied: int = 0
    steps_failed: int = 0
    chain_gaps_detected: int = 0
    version_reads: int = 0


#: Where each structure kind's chain currently tops out. A module-level constant lookup table,
#: so `FrozenDict` per §2.1.1 — and the value a fresh install is created at, which is why it
#: lives beside the contracts rather than inside the registry: `registry.py` checks its own
#: registered steps against this, and a registry that supplied its own target would always
#: agree with itself.
CURRENT_VERSIONS: FrozenDict = FrozenDict(
    {
        StructureKind.DATABASE_SCHEMA: 1,
        StructureKind.CONFIG: 1,
        StructureKind.VENDOR_DATA: 1,
    }
)


__all__ = [
    "CURRENT_VERSIONS",
    "ChainIntegrityReport",
    "MigrationMetrics",
    "MigrationOutcome",
    "MigrationResult",
    "MigrationStep",
    "SchemaVersion",
    "StepResult",
    "StructureKind",
    "utcnow",
]

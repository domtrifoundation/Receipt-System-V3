"""Walks a structure from its current version to the target (§3, §4, §8).

§3's own sketch is four lines, and the shape here is the same — one step at a time, in order,
each writing through Persistence's normal path so it is atomic and Historian-logged without
this package owning any rollback machinery of its own (§1).

What the sketch leaves implicit and this module makes explicit:

* **A failed or missing step stops the walk**, and `MigrationResult.reached_version` reports
  how far it actually got. Continuing past a gap would leave the structure in a state no
  version number describes and no later step was written to expect — see `errors.py` for why
  that is worse than not migrating at all.
* **A step that finds its change already present is a success**, distinguished as
  `ALREADY_APPLIED`. §8 asks for this directly: migrations get re-run after an interrupted
  batch, and a re-run must be "a safe no-op, not a duplicate application".
* **A step's own exception never propagates.** §4's bulk case walks every user's database at
  once; one user's row violating an assumption must not take the batch down with it.

**Bulk parallelism is not here, on purpose.** §4 routes a multi-tenant batch through Background
Workers' `CPU_PROCESS` class rather than this API building its own parallel dispatch — so
`migrate_many` below is a plain sequential loop that a `CPU_PROCESS` job can call per structure,
not a thread pool this module manages (`docs/PRINCIPLES.md` §1.5).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime

from .contracts import (
    CURRENT_VERSIONS,
    MigrationOutcome,
    MigrationResult,
    StepResult,
    StructureKind,
    utcnow,
)
from .errors import (
    InvalidVersionRange,
    MigrationError,
    MissingMigrationStep,
    code_for,
    summary_for,
)
from .metrics import MigrationMetricsCollector
from .registry import MigrationRegistry, RegisteredStep


class MigrationRunner:
    """Applies registered steps in order. One instance per Migration process."""

    def __init__(
        self,
        registry: MigrationRegistry,
        *,
        metrics: MigrationMetricsCollector | None = None,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._registry = registry
        self._metrics = metrics or MigrationMetricsCollector()
        self._now = now

    @property
    def metrics(self) -> MigrationMetricsCollector:
        return self._metrics

    async def migrate(
        self,
        structure_id: str,
        kind: StructureKind,
        current_version: int,
        target_version: int | None = None,
    ) -> MigrationResult:
        """Walk one structure forward, one bump at a time (§3).

        `target_version=None` means "this build's current version for that kind" — which is the
        ordinary case, since §9 ties a schema bump to the release that ships it: new code and
        the schema it expects arrive together, so the target is whatever this release knows
        about, never a number a caller supplies from elsewhere.
        """
        target = CURRENT_VERSIONS.get(kind, current_version) if target_version is None else target_version
        self._metrics.increment("migrations_attempted")

        if current_version < 0 or target < current_version:
            exc = InvalidVersionRange(
                f"cannot walk {kind.value} from {current_version} to {target}; "
                "this registry holds forward N->N+1 steps only"
            )
            return MigrationResult(
                structure_id=structure_id,
                kind=kind,
                from_version=current_version,
                reached_version=current_version,
                target_version=target,
                error_code=code_for(exc),
                error_detail=str(exc),
            )

        results: list[StepResult] = []
        reached = current_version

        for version in range(current_version, target):
            try:
                registered = self._registry.get_step(kind, version)
            except MissingMigrationStep as exc:
                self._metrics.increment("chain_gaps_detected")
                return MigrationResult(
                    structure_id=structure_id,
                    kind=kind,
                    from_version=current_version,
                    reached_version=reached,
                    target_version=target,
                    steps=tuple(results),
                    error_code=code_for(exc),
                    error_detail=str(exc),
                )

            outcome = await self._apply_one(registered, structure_id)
            results.append(outcome)
            if outcome.outcome is MigrationOutcome.FAILED:
                return MigrationResult(
                    structure_id=structure_id,
                    kind=kind,
                    from_version=current_version,
                    reached_version=reached,
                    target_version=target,
                    steps=tuple(results),
                    error_code=outcome.error_code,
                    error_detail=outcome.error_detail,
                )
            reached = registered.step.to_version

        return MigrationResult(
            structure_id=structure_id,
            kind=kind,
            from_version=current_version,
            reached_version=reached,
            target_version=target,
            steps=tuple(results),
        )

    async def _apply_one(self, registered: RegisteredStep, structure_id: str) -> StepResult:
        """Run one step, converting anything it raises into data (§4.1)."""
        started = self._now()
        try:
            did_work = await registered.apply(structure_id)
        except MigrationError as exc:
            self._metrics.increment("steps_failed")
            return StepResult(
                step=registered.step,
                structure_id=structure_id,
                outcome=MigrationOutcome.FAILED,
                started_at=started,
                finished_at=self._now(),
                error_code=code_for(exc),
                error_detail=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - one structure must not fail a whole batch
            self._metrics.increment("steps_failed")
            return StepResult(
                step=registered.step,
                structure_id=structure_id,
                outcome=MigrationOutcome.FAILED,
                started_at=started,
                finished_at=self._now(),
                error_code="STEP_FAILED",
                error_detail=f"{type(exc).__name__}: {exc}",
            )

        if did_work:
            self._metrics.increment("steps_applied")
            outcome = MigrationOutcome.APPLIED
        else:
            self._metrics.increment("steps_already_applied")
            outcome = MigrationOutcome.ALREADY_APPLIED
        return StepResult(
            step=registered.step,
            structure_id=structure_id,
            outcome=outcome,
            started_at=started,
            finished_at=self._now(),
        )

    async def migrate_many(
        self,
        structure_ids: Sequence[str],
        kind: StructureKind,
        current_version: int,
        target_version: int | None = None,
    ) -> tuple[MigrationResult, ...]:
        """Walk several structures, each independently (§4).

        Sequential on purpose. §4 sends the multi-tenant batch through Background Workers'
        `CPU_PROCESS` class rather than having this API build its own parallel dispatch, so
        this is the per-structure loop such a job calls — not a pool this module manages.

        One structure failing never stops the others: a batch that halted on the first bad
        database would leave every user after it in the list un-migrated, with nothing to say
        which ones those were.
        """
        results: list[MigrationResult] = []
        for structure_id in structure_ids:
            results.append(await self.migrate(structure_id, kind, current_version, target_version))
        return tuple(results)


def summarize_failures(results: Iterable[MigrationResult]) -> tuple[str, ...]:
    """One line per structure that did not reach its target.

    A batch of five hundred returns five hundred results, and the two that failed are what
    someone actually needs. Deriving that here means a caller does not write its own filter and
    quietly disagree about what counts as failure — an incomplete walk with no error code
    (a gap found before any step ran) counts, and would be missed by a check on `ok` alone.
    """
    return tuple(
        f"{r.structure_id}: reached {r.reached_version}/{r.target_version}"
        + (f" — {summary_for(r.error_code)}" if r.error_code else "")
        for r in results
        if not r.complete
    )


__all__ = ["MigrationRunner", "summarize_failures"]

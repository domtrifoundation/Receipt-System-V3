"""The chain, its integrity, and idempotent re-runs (§1, §3, §8).

Both testing hooks §8 names:

* **Chain-integrity test** — "confirms every registered version has exactly one N→N+1 step
  defined, no gaps — a missing step should fail CI, not be discovered mid-migration on a live
  system."
* **Idempotency test** — "re-running an already-applied migration step is a safe no-op, not a
  duplicate application — worth explicit coverage given migrations sometimes need to be re-run
  after an interrupted batch."

The second one is where the interesting design pressure sits. The runner cannot possibly know
whether a structure already carries a change — only the step knows what to look for — so
idempotency is a contract the step fulfils by returning whether it did real work. These tests
therefore check both halves: that a step reporting "already applied" is treated as a success
and counted separately, and that an interrupted batch re-run lands where it should.
"""

from __future__ import annotations

import pytest

from core.migration.contracts import (
    CURRENT_VERSIONS,
    MigrationOutcome,
    MigrationStep,
    StructureKind,
)
from core.migration.errors import (
    DuplicateMigrationStep,
    MissingMigrationStep,
    MultiVersionStep,
)
from core.migration.registry import MigrationRegistry, default_registry
from core.migration.runner import MigrationRunner, summarize_failures

from .conftest import CountingStep, run, step_for

SCHEMA = StructureKind.DATABASE_SCHEMA


# ------------------------------------------------------------- §1's chained-never-direct


def test_a_step_spanning_two_versions_is_rejected_at_registration():
    """§1: "N→N+2 is always N→N+1→N+2, chained, never a shortcut".

    Rejected when it is registered rather than when it runs, because the risk §1 names is that
    "two different code paths could produce the same end state" — and the two only disagree
    once someone edits one of them, which is far too late to discover the shortcut exists.
    """
    registry = MigrationRegistry()
    shortcut = MigrationStep(
        kind=SCHEMA, from_version=1, to_version=3, description="skips a version"
    )

    with pytest.raises(MultiVersionStep):
        registry.register(shortcut, CountingStep())


def test_two_steps_for_one_bump_are_rejected():
    """Which one runs would otherwise depend on import order.

    A migration whose behaviour depends on import order is not reproducible, which is the one
    property a migration chain has to have.
    """
    registry = MigrationRegistry()
    registry.register(step_for(1), CountingStep())

    with pytest.raises(DuplicateMigrationStep):
        registry.register(step_for(1), CountingStep())


def test_a_single_bump_is_accepted():
    """The positive case, so the two rejections above are not passing vacuously."""
    registry = MigrationRegistry()
    registry.register(step_for(1), CountingStep())

    assert registry.has_step(SCHEMA, 1)


def test_walking_two_versions_runs_two_steps_in_order(runner_with):
    """The chain is walked one bump at a time, never jumped."""
    first, second = CountingStep(), CountingStep()
    runner = runner_with({1: first, 2: second})

    result = run(runner.migrate("db-1", SCHEMA, current_version=1, target_version=3))

    assert result.ok
    assert result.complete
    assert [s.step.from_version for s in result.steps] == [1, 2]
    assert first.calls == 1
    assert second.calls == 1


# ---------------------------------------------------------------- §8's chain integrity


def test_a_gap_in_the_chain_is_reported_before_anything_runs(runner_with):
    """§8's chain-integrity hook, as the check meant to run in CI.

    The report names the missing bump rather than returning a bare False, so the failure says
    which step someone forgot to write.
    """
    registry = MigrationRegistry()
    registry.register(step_for(1), CountingStep())
    registry.register(step_for(3), CountingStep())

    report = registry.check_chain(SCHEMA, target_version=4)

    assert not report.intact
    assert report.missing_bumps == (2,)


def test_an_unbroken_chain_reports_intact():
    registry = MigrationRegistry()
    registry.register(step_for(1), CountingStep())
    registry.register(step_for(2), CountingStep())

    assert registry.check_chain(SCHEMA, target_version=3).intact


def test_integrity_is_measured_from_version_one_not_the_lowest_registered_step():
    """A chain whose first step is 3→4 is missing 1→2 and 2→3, not a chain with a high floor.

    Starting the check at the lowest *registered* version would define exactly that gap out of
    existence — and it is the gap a fresh install hits, since a fresh install starts at 1.
    """
    registry = MigrationRegistry()
    registry.register(step_for(3), CountingStep())

    report = registry.check_chain(SCHEMA, target_version=4)

    assert report.missing_bumps == (1, 2)


def test_the_shipped_registry_is_intact_for_every_structure_kind():
    """The real check, against the real registry — this is what would fail CI.

    Every kind is at version 1 today so every chain is trivially intact; the moment
    `CURRENT_VERSIONS` moves to 2 without a 1→2 step registered, this fails, which is exactly
    what §8 asks for.
    """
    registry = default_registry()

    for kind, target in CURRENT_VERSIONS.items():
        report = registry.check_chain(kind, target_version=target)
        assert report.intact, f"{kind.value} chain is broken: {report.missing_bumps}"


def test_a_missing_step_stops_the_walk_rather_than_skipping_it(runner_with):
    """Continuing past a gap leaves the structure in a state no version describes.

    The result reports how far it actually got, which is the only honest answer — a caller
    that assumed the target was reached would then run code against a schema that does not
    exist.
    """
    runner = runner_with({1: CountingStep()})

    result = run(runner.migrate("db-1", SCHEMA, current_version=1, target_version=3))

    assert not result.ok
    assert result.error_code == "MISSING_MIGRATION_STEP"
    assert result.reached_version == 2
    assert not result.complete


def test_a_registry_lookup_for_a_missing_bump_raises_rather_than_returning_none():
    """Every caller would have to turn a `None` into a stop, and one that forgot would skip
    the gap silently — the half-migrated state this package treats as worse than no migration."""
    with pytest.raises(MissingMigrationStep):
        MigrationRegistry().get_step(SCHEMA, 1)


# ------------------------------------------------------------------- §8's idempotency


def test_a_step_reporting_already_applied_is_a_success_not_a_failure(runner_with):
    """§8's idempotency hook: a re-run is "a safe no-op, not a duplicate application"."""
    runner = runner_with({1: CountingStep(did_work=False)})

    result = run(runner.migrate("db-1", SCHEMA, current_version=1, target_version=2))

    assert result.ok
    assert result.complete
    assert result.steps[0].outcome is MigrationOutcome.ALREADY_APPLIED


def test_already_applied_steps_are_counted_separately_from_real_work(runner_with):
    """The two must stay tellable apart.

    A batch re-run after an interruption should be mostly already-applied. If it reported
    everything as newly applied, either the first run did less than it said or the steps' own
    checks are broken — and both are invisible without this split.
    """
    runner = runner_with({1: CountingStep(did_work=True), 2: CountingStep(did_work=False)})

    result = run(runner.migrate("db-1", SCHEMA, current_version=1, target_version=3))

    assert len(result.steps) == 2
    assert result.applied_count == 1
    snapshot = runner.metrics.snapshot()
    assert snapshot.steps_applied == 1
    assert snapshot.steps_already_applied == 1


def test_re_running_a_completed_migration_does_no_duplicate_work(runner_with):
    """The interrupted-batch case §8 names, end to end.

    The steps report already-applied on the second pass — as a real step would, having checked
    and found its change present — and the result is still a complete, successful migration.
    """
    first, second = CountingStep(), CountingStep()
    runner = runner_with({1: first, 2: second})
    run(runner.migrate("db-1", SCHEMA, current_version=1, target_version=3))

    first.did_work = False
    second.did_work = False
    again = run(runner.migrate("db-1", SCHEMA, current_version=1, target_version=3))

    assert again.ok
    assert again.complete
    assert again.applied_count == 0


def test_a_migration_with_nothing_to_do_is_complete_immediately(runner_with):
    """Already at the target — no steps, no error, complete."""
    runner = runner_with({})

    result = run(runner.migrate("db-1", SCHEMA, current_version=2, target_version=2))

    assert result.ok
    assert result.complete
    assert result.steps == ()


# ----------------------------------------------------------------- failure containment


def test_a_step_that_raises_becomes_data_not_an_exception(runner_with):
    """§4's bulk case walks every user's database; one bad row must not take the batch down."""

    class Exploding(CountingStep):
        async def __call__(self, structure_id: str) -> bool:
            raise RuntimeError("a row violated an assumption")

    runner = runner_with({1: Exploding()})

    result = run(runner.migrate("db-1", SCHEMA, current_version=1, target_version=2))

    assert not result.ok
    assert result.steps[0].outcome is MigrationOutcome.FAILED
    assert "violated an assumption" in result.error_detail


def test_a_failed_step_stops_the_walk_at_its_last_good_version(runner_with):
    """The structure is at 2, not 3, and the result says so.

    Reporting the target would leave a caller running code against a schema the structure never
    reached — the single most consequential lie this API could tell.
    """

    class Exploding(CountingStep):
        async def __call__(self, structure_id: str) -> bool:
            raise RuntimeError("boom")

    third = CountingStep()
    runner = runner_with({1: CountingStep(), 2: Exploding(), 3: third})

    result = run(runner.migrate("db-1", SCHEMA, current_version=1, target_version=4))

    assert result.reached_version == 2
    assert third.calls == 0


def test_a_downgrade_is_refused(runner_with):
    """This registry holds forward steps only.

    Walking backwards would need inverse steps nobody wrote, and guessing at one is how a
    "rollback" silently destroys data. Reverting is Persistence's Historian-backed job (§1).
    """
    runner = runner_with({1: CountingStep()})

    result = run(runner.migrate("db-1", SCHEMA, current_version=3, target_version=1))

    assert not result.ok
    assert result.error_code == "INVALID_VERSION_RANGE"


# --------------------------------------------------------------------- the bulk case


def test_one_structure_failing_never_stops_the_others(runner_with):
    """§4's batch walks every user; halting on the first bad database would leave every user
    after it un-migrated with nothing to say which ones those were."""

    class FailsOne(CountingStep):
        async def __call__(self, structure_id: str) -> bool:
            if structure_id == "db-2":
                raise RuntimeError("this one is broken")
            self.calls += 1
            return True

    runner = runner_with({1: FailsOne()})

    results = run(runner.migrate_many(["db-1", "db-2", "db-3"], SCHEMA, 1, 2))

    assert [r.ok for r in results] == [True, False, True]


def test_a_batch_summary_names_only_what_did_not_finish(runner_with):
    """Five hundred results, and the two that failed are what someone actually needs."""

    class FailsOne(CountingStep):
        async def __call__(self, structure_id: str) -> bool:
            if structure_id == "db-2":
                raise RuntimeError("broken")
            return True

    runner = runner_with({1: FailsOne()})
    results = run(runner.migrate_many(["db-1", "db-2", "db-3"], SCHEMA, 1, 2))

    failures = summarize_failures(results)

    assert len(failures) == 1
    assert failures[0].startswith("db-2:")


def test_the_target_defaults_to_this_builds_current_version(runner_with):
    """§9: a schema bump ships with the release that expects it.

    So the target is whatever this build knows about, never a number a caller supplies from
    elsewhere — new code and its schema arrive together, never one ahead of the other.
    """
    runner = runner_with({})

    result = run(runner.migrate("db-1", SCHEMA, current_version=1))

    assert result.target_version == CURRENT_VERSIONS[SCHEMA]

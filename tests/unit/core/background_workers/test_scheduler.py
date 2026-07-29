"""Dispatch, routing, the idle gate and §10's failure guard (§3, §4, §9, §10).

Two of §9's three named testing hooks live here:

* **Consecutive-failure guard test** — "confirms a job failing five times in a row genuinely
  auto-disables and surfaces an `ATTENTION`-level entry, rather than retrying indefinitely."
* **Idle-scope test** — "confirms a per-user-scoped job checks that specific user's idle state
  while a system-wide job doesn't check any — the distinction §10 resolves is only real if
  something enforces it."

The third (registry completeness) is in `test_registry_completeness.py`.

Underneath all of them is the property this package exists to hold: **nothing a registered job
does can take the scheduler down**. Every other registered job depends on that, and the silence
that follows a scheduler crash — no retention purges, no session cleanup, no archive sync —
would be far worse than any single job's failure.
"""

from __future__ import annotations

from concurrent import futures

import pytest

from core.background_workers.contracts import (
    MAX_CONSECUTIVE_FAILURES,
    JobClass,
    JobOutcome,
)
from core.background_workers.idle_detection import (
    ExecutionCoreUnavailable,
    IdleDetector,
    StaticRunState,
)
from core.background_workers.metrics import BackgroundWorkersMetricsCollector
from core.background_workers.registry import JobRegistry
from core.background_workers.scheduler import JobScheduler

from .conftest import RecordingHandler, registration


def _scheduler(registry, clock, *, idle=None, metrics=None, **kwargs):
    return JobScheduler(
        registry,
        idle=idle or IdleDetector(StaticRunState({})),
        metrics=metrics,
        now=clock,
        **kwargs,
    )


# ------------------------------------------------------------------ ordinary dispatch


def test_a_due_job_runs(registry, clock, idle_everywhere):
    handler = RecordingHandler()
    registry.register(registration(), handler)
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)

    result = scheduler.dispatch("log_retention_purge")

    assert result.outcome is JobOutcome.SUCCEEDED
    assert handler.calls == 1


def test_a_newly_registered_job_is_due_immediately(registry, clock, idle_everywhere):
    """Otherwise a weekly job does nothing for a week after deployment.

    That silence would look exactly like a broken scheduler, and on a job like blob-backup
    spot-verification it would mean the first real check happens seven days after the operator
    thought they had enabled it.
    """
    handler = RecordingHandler()
    registry.register(registration(interval_seconds=7 * 24 * 60 * 60), handler)
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)

    assert scheduler.dispatch("log_retention_purge").outcome is JobOutcome.SUCCEEDED


def test_a_job_run_again_before_its_interval_is_skipped_not_run(
    registry, clock, idle_everywhere
):
    handler = RecordingHandler()
    registry.register(registration(interval_seconds=3600), handler)
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)
    scheduler.dispatch("log_retention_purge")

    clock.advance(60)
    result = scheduler.dispatch("log_retention_purge")

    assert result.outcome is JobOutcome.SKIPPED_NOT_DUE
    assert handler.calls == 1


def test_a_job_runs_again_once_its_interval_has_elapsed(registry, clock, idle_everywhere):
    handler = RecordingHandler()
    registry.register(registration(interval_seconds=3600), handler)
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)
    scheduler.dispatch("log_retention_purge")

    clock.advance(3601)
    scheduler.dispatch("log_retention_purge")

    assert handler.calls == 2


def test_an_event_triggered_job_never_fires_on_a_timer(registry, clock, idle_everywhere):
    """§6.2: `interval_seconds=None` means something else fires this.

    Telemetrees' signal-compilation job is the real case — it runs when a diagnostic signal
    appears, and a timer firing it would compile issues out of nothing.
    """
    handler = RecordingHandler()
    registry.register(registration(interval_seconds=None), handler)
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)

    result = scheduler.dispatch("log_retention_purge")

    assert result.outcome is JobOutcome.SKIPPED_NOT_DUE
    assert handler.calls == 0


def test_an_event_triggered_job_still_runs_when_forced(registry, clock, idle_everywhere):
    """Which is how the API that produced the signal actually fires it."""
    handler = RecordingHandler()
    registry.register(registration(interval_seconds=None), handler)
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)

    result = scheduler.dispatch("log_retention_purge", force=True)

    assert result.outcome is JobOutcome.SUCCEEDED
    assert handler.calls == 1


# ---------------------------------------------------------------------- the idle gate


def test_an_idle_only_job_is_held_back_while_the_scope_is_busy(registry, clock):
    """§4: idle-time work yields to active foreground work.

    V2 already proved this behaviour was right; §4 keeps it deliberately rather than
    rederiving it.
    """
    handler = RecordingHandler()
    registry.register(registration(idle_only=True), handler)
    busy = IdleDetector(StaticRunState({"global": 3}))
    scheduler = _scheduler(registry, clock, idle=busy)

    result = scheduler.dispatch("log_retention_purge")

    assert result.outcome is JobOutcome.SKIPPED_NOT_IDLE
    assert "3 active run(s)" in result.error_detail
    assert handler.calls == 0


def test_a_per_user_job_checks_that_users_idle_state_not_the_global_one(registry, clock):
    """§9's idle-scope hook, first half.

    One user's active session has no business blocking another user's unrelated archive sync.
    The system as a whole is busy here; the scope this job cares about is not.
    """
    handler = RecordingHandler()
    registry.register(
        registration(job_id="archive_sync_execution", idle_only=True, scope="user-1"), handler
    )
    busy_elsewhere = IdleDetector(StaticRunState({"global": 5, "user-2": 5, "user-1": 0}))
    scheduler = _scheduler(registry, clock, idle=busy_elsewhere)

    result = scheduler.dispatch("archive_sync_execution")

    assert result.outcome is JobOutcome.SUCCEEDED
    assert handler.calls == 1


def test_a_per_user_job_is_held_back_when_that_user_is_busy(registry, clock):
    handler = RecordingHandler()
    registry.register(
        registration(job_id="archive_sync_execution", idle_only=True, scope="user-1"), handler
    )
    user_busy = IdleDetector(StaticRunState({"global": 0, "user-1": 2}))
    scheduler = _scheduler(registry, clock, idle=user_busy)

    assert scheduler.dispatch("archive_sync_execution").outcome is JobOutcome.SKIPPED_NOT_IDLE


def test_a_system_wide_job_that_is_not_idle_only_checks_no_ones_idle_state(registry, clock):
    """§9's idle-scope hook, second half.

    Log retention and Dependencies Warden polling touch no per-user resource, so they have no
    reason to consult anyone's run state — and a busy system must not silently stop them.
    """
    handler = RecordingHandler()
    registry.register(registration(idle_only=False), handler)
    everything_busy = IdleDetector(StaticRunState({"global": 99}))
    scheduler = _scheduler(registry, clock, idle=everything_busy)

    assert scheduler.dispatch("log_retention_purge").outcome is JobOutcome.SUCCEEDED


def test_an_unavailable_idle_check_holds_the_job_back_rather_than_running_it(registry, clock):
    """Unavailable means not idle — the one conservative default in this package.

    Execution Core does not exist in this build, so this is the real production path today.
    Running a `CPU_PROCESS` sweep while unable to confirm the system is quiet costs the user's
    actual work; skipping it costs one interval.
    """
    handler = RecordingHandler()
    registry.register(registration(idle_only=True), handler)
    metrics = BackgroundWorkersMetricsCollector()
    scheduler = _scheduler(
        registry,
        clock,
        idle=IdleDetector(ExecutionCoreUnavailable(), metrics=metrics),
        metrics=metrics,
    )

    result = scheduler.dispatch("log_retention_purge")

    assert result.outcome is JobOutcome.SKIPPED_NOT_IDLE
    assert handler.calls == 0
    assert metrics.snapshot().idle_checks_unavailable == 1


def test_forcing_a_job_bypasses_the_idle_gate(registry, clock):
    handler = RecordingHandler()
    registry.register(registration(idle_only=True), handler)
    scheduler = _scheduler(registry, clock, idle=IdleDetector(StaticRunState({"global": 9})))

    assert scheduler.dispatch("log_retention_purge", force=True).outcome is JobOutcome.SUCCEEDED


# ------------------------------------------------------------------ §10's failure guard


def test_a_failing_job_is_recorded_not_raised(registry, clock, idle_everywhere):
    """The property every other registered job depends on."""
    registry.register(registration(), RecordingHandler(always_fail=True))
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)

    result = scheduler.dispatch("log_retention_purge")

    assert result.outcome is JobOutcome.FAILED
    assert "job failed" in result.error_detail


def test_five_consecutive_failures_auto_disable_the_job(registry, clock, idle_everywhere):
    """§9's consecutive-failure guard hook, and §10's resolved mechanism.

    Retrying forever is V2's own known failure mode. A job that has failed five times running
    is not going to succeed on the sixth without someone looking at it.
    """
    handler = RecordingHandler(always_fail=True)
    registry.register(registration(interval_seconds=1), handler)
    metrics = BackgroundWorkersMetricsCollector()
    scheduler = _scheduler(registry, clock, idle=idle_everywhere, metrics=metrics)

    results = []
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        results.append(scheduler.dispatch("log_retention_purge"))
        clock.advance(2)

    health = registry.health("log_retention_purge")
    assert health.disabled
    assert health.consecutive_failures == MAX_CONSECUTIVE_FAILURES
    assert results[-1].tripped_failure_guard
    assert metrics.snapshot().jobs_auto_disabled == 1


def test_only_the_tripping_dispatch_carries_the_guard_flag(registry, clock, idle_everywhere):
    """So a caller surfaces exactly one ATTENTION entry, not five.

    An alert that fires on every failure trains an operator to ignore it, which is the same
    reasoning Health's own drift check uses about crying wolf.
    """
    registry.register(registration(interval_seconds=1), RecordingHandler(always_fail=True))
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)

    tripped = []
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        tripped.append(scheduler.dispatch("log_retention_purge").tripped_failure_guard)
        clock.advance(2)

    assert tripped.count(True) == 1


def test_a_disabled_job_stops_running_entirely(registry, clock, idle_everywhere):
    handler = RecordingHandler(always_fail=True)
    registry.register(registration(interval_seconds=1), handler)
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        scheduler.dispatch("log_retention_purge")
        clock.advance(2)
    calls_at_disable = handler.calls

    result = scheduler.dispatch("log_retention_purge")

    assert result.outcome is JobOutcome.SKIPPED_DISABLED
    assert handler.calls == calls_at_disable


def test_forcing_does_not_bypass_the_disabled_guard(registry, clock, idle_everywhere):
    """§10 makes re-enabling an explicit staff action *after investigating*.

    A force flag that also cleared the guard would be a way to keep a broken job limping
    without anyone ever looking at why — the exact outcome the guard exists to force.
    """
    registry.register(registration(interval_seconds=1), RecordingHandler(always_fail=True))
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        scheduler.dispatch("log_retention_purge")
        clock.advance(2)

    assert (
        scheduler.dispatch("log_retention_purge", force=True).outcome
        is JobOutcome.SKIPPED_DISABLED
    )


def test_a_success_resets_the_consecutive_counter(registry, clock, idle_everywhere):
    """The guard is about *consecutive* failures — an intermittent job must not accumulate.

    A flaky network job failing four times over a month, succeeding in between, is not the
    permanently-broken case §10 is aimed at.
    """
    handler = RecordingHandler(fail_times=4)
    registry.register(registration(interval_seconds=1), handler)
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)

    for _ in range(6):
        scheduler.dispatch("log_retention_purge")
        clock.advance(2)

    health = registry.health("log_retention_purge")
    assert not health.disabled
    assert health.consecutive_failures == 0


def test_skips_never_count_toward_the_failure_guard(registry, clock):
    """Otherwise the healthiest jobs on the busiest systems auto-disable first.

    A job correctly yielding to foreground work every hour for a week has not failed once, and
    counting those skips would be precisely backwards.
    """
    registry.register(registration(idle_only=True, interval_seconds=1), RecordingHandler())
    scheduler = _scheduler(registry, clock, idle=IdleDetector(StaticRunState({"global": 4})))

    for _ in range(MAX_CONSECUTIVE_FAILURES * 2):
        scheduler.dispatch("log_retention_purge")
        clock.advance(2)

    health = registry.health("log_retention_purge")
    assert not health.disabled
    assert health.consecutive_failures == 0


def test_re_enabling_is_an_explicit_action_that_clears_the_counter(
    registry, clock, idle_everywhere
):
    handler = RecordingHandler(always_fail=True)
    registry.register(registration(interval_seconds=1), handler)
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        scheduler.dispatch("log_retention_purge")
        clock.advance(2)

    cleared = registry.enable("log_retention_purge", cleared_by="staff-1")

    assert not cleared.disabled
    assert cleared.consecutive_failures == 0
    assert "staff-1" in cleared.disabled_reason
    assert scheduler.dispatch("log_retention_purge").outcome is JobOutcome.FAILED


# ----------------------------------------------------------------------- §3 routing


@pytest.mark.parametrize(
    "job_class", [JobClass.ASYNC_IO, JobClass.NATIVE_THREAD, JobClass.CPU_PROCESS]
)
def test_every_job_class_actually_runs_its_handler(registry, clock, idle_everywhere, job_class):
    """Routing must not be able to silently drop a class.

    A class that fell through to no substrate would leave those jobs never running, with a
    `SUCCEEDED` result to say otherwise — the worst possible failure for unattended work.
    """
    handler = RecordingHandler()
    registry.register(registration(job_class=job_class), handler)
    scheduler = _scheduler(
        registry, clock, idle=idle_everywhere, thread_pool=futures.ThreadPoolExecutor(1)
    )

    assert scheduler.dispatch("log_retention_purge").outcome is JobOutcome.SUCCEEDED
    assert handler.calls == 1


def test_a_native_thread_job_is_submitted_to_the_thread_pool(registry, clock, idle_everywhere):
    """§3's routing is a design requirement, not a detail — so it is asserted, not assumed."""
    submitted: list[object] = []

    class RecordingPool(futures.Executor):
        def submit(self, fn, *args, **kwargs):
            submitted.append(fn)
            return super().submit(fn, *args, **kwargs)

    pool = RecordingPool()
    registry.register(registration(job_class=JobClass.NATIVE_THREAD), RecordingHandler())
    scheduler = _scheduler(registry, clock, idle=idle_everywhere, thread_pool=pool)

    scheduler.dispatch("log_retention_purge")

    assert len(submitted) == 1


def test_an_async_io_job_never_touches_a_pool(registry, clock, idle_everywhere):
    """An I/O job on a process pool pays a pickling round trip for nothing."""
    submitted: list[object] = []

    class RecordingPool(futures.Executor):
        def submit(self, fn, *args, **kwargs):
            submitted.append(fn)
            return super().submit(fn, *args, **kwargs)

    registry.register(registration(job_class=JobClass.ASYNC_IO), RecordingHandler())
    scheduler = _scheduler(
        registry, clock, idle=idle_everywhere, thread_pool=RecordingPool(), process_pool=RecordingPool()
    )

    scheduler.dispatch("log_retention_purge")

    assert submitted == []


# ------------------------------------------------------------------- the tick, and §4.1


def test_one_bad_job_never_stops_the_others_in_a_tick(registry, clock, idle_everywhere):
    """The independence that makes `dispatch_due` safe to run unattended."""
    good = RecordingHandler()
    registry.register(registration(job_id="log_retention_purge"), RecordingHandler(always_fail=True))
    registry.register(registration(job_id="expired_session_cleanup", owning_api="auth"), good)
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)

    results = scheduler.dispatch_due()

    assert {r.outcome for r in results} == {JobOutcome.FAILED, JobOutcome.SUCCEEDED}
    assert good.calls == 1


def test_next_due_reports_the_soonest_timer_job_first(registry, clock, idle_everywhere):
    """§4.1's operator-facing view, preserved from V2 as genuinely useful transparency."""
    registry.register(registration(job_id="log_retention_purge", interval_seconds=3600), RecordingHandler())
    registry.register(
        registration(job_id="expired_session_cleanup", owning_api="auth", interval_seconds=86400),
        RecordingHandler(),
    )
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)
    scheduler.dispatch_due()

    estimates = scheduler.next_due()

    assert [e.job_id for e in estimates] == ["log_retention_purge", "expired_session_cleanup"]
    assert all(e.approximate for e in estimates)


def test_next_due_marks_a_job_blocked_by_a_busy_scope(registry, clock):
    """Why the estimate is explicitly best-effort: idle conditions gate the real fire time."""
    registry.register(registration(idle_only=True), RecordingHandler())
    scheduler = _scheduler(registry, clock, idle=IdleDetector(StaticRunState({"global": 2})))

    assert scheduler.next_due()[0].blocked_by_idle


def test_next_due_omits_event_triggered_and_disabled_jobs(registry, clock, idle_everywhere):
    registry.register(registration(job_id="telemetrees_signal", interval_seconds=None), RecordingHandler())
    scheduler = _scheduler(registry, clock, idle=idle_everywhere)

    assert scheduler.next_due() == ()


def test_dispatching_an_unknown_job_raises_internally(registry, clock, idle_everywhere):
    from core.background_workers.errors import UnknownJob

    scheduler = _scheduler(registry, clock, idle=idle_everywhere)

    with pytest.raises(UnknownJob):
        scheduler.dispatch("never_registered")

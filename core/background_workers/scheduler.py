"""Routes each job to the right pool per its declared class, and guards against a bad one (§3, §4, §10).

Three responsibilities, in the order a dispatch hits them:

1. **Should this run at all** — is it disabled (§10's guard), is it due (its own interval), and
   if it is `idle_only`, is the relevant scope actually quiet (§4).
2. **Run it on the right substrate** (§3) — the event loop for `ASYNC_IO`, a thread pool for
   `NATIVE_THREAD`, a process pool for `CPU_PROCESS`. §3 states this as a design requirement
   rather than a detail, and the cost of getting it wrong is asymmetric but real in both
   directions: an I/O job on a process pool pays a pickling round trip for nothing, and a
   CPU-bound pure-Python job on the event loop blocks every other job behind it.
3. **Record what happened**, including tripping §10's failure guard on the fifth consecutive
   failure.

**Nothing a job does may propagate out of here.** A registered job raising, hanging, or
returning nonsense becomes a `FAILED` result and the loop continues. A scheduler that one bad
job could take down would take every *other* registered job with it — and the resulting silence
across log retention, session cleanup, archive sync and every maintenance sweep would be far
worse than the one job's own failure (`docs/PRINCIPLES.md` §4.4, and this package's `errors.py`
explains the asymmetry with §10's guard at length).

**The pools are injected, not owned.** §1 is explicit that this API does not run a separate
worker-server process — non-LLM workers run in-process within Execution Core's own process. So
the executors come from whoever hosts this scheduler; constructing them here would quietly make
this API the infrastructure §1 says it must not become.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent import futures
from datetime import datetime, timedelta

from .contracts import (
    MAX_CONSECUTIVE_FAILURES,
    GLOBAL_SCOPE,
    JobClass,
    JobHealth,
    JobOutcome,
    JobRegistration,
    JobRunResult,
    NextDueEstimate,
    utcnow,
)
from .errors import JobDisabled, UnknownJob
from .idle_detection import IdleDetector
from .metrics import BackgroundWorkersMetricsCollector
from .registry import JobRegistry

#: What a registered job's handler looks like. Deliberately takes no arguments and returns
#: nothing: this API owns no business logic (§1), so it has nothing meaningful to pass in and
#: nothing meaningful to do with a return value. A job that needs context closes over it.
JobHandler = Callable[[], None]


class JobScheduler:
    """Dispatches registered jobs. One instance per hosting process."""

    def __init__(
        self,
        registry: JobRegistry,
        *,
        idle: IdleDetector | None = None,
        thread_pool: futures.Executor | None = None,
        process_pool: futures.Executor | None = None,
        metrics: BackgroundWorkersMetricsCollector | None = None,
        now: Callable[[], datetime] = utcnow,
        default_timeout: float | None = None,
    ) -> None:
        self._registry = registry
        self._metrics = metrics or BackgroundWorkersMetricsCollector()
        self._idle = idle or IdleDetector(metrics=self._metrics)
        self._thread_pool = thread_pool
        self._process_pool = process_pool
        self._now = now
        self._default_timeout = default_timeout
        self._lock = threading.Lock()

    # ------------------------------------------------------------------- dispatch

    def dispatch(self, job_id: str, *, force: bool = False) -> JobRunResult:
        """Run one job if it should run, and record the outcome either way.

        `force` skips the due-time and idle checks — an operator saying "run this now" — but
        deliberately does **not** skip the disabled check. §10 makes re-enabling an explicit
        staff action after investigating; a force flag that also cleared the guard would be a
        way to keep a broken job limping without ever looking at it.
        """
        registration = self._registry.require(job_id)
        health = self._registry.health(job_id)
        started = self._now()

        if health.disabled:
            self._metrics.increment("skipped_disabled")
            return self._record(
                registration,
                health,
                JobOutcome.SKIPPED_DISABLED,
                started,
                detail=str(JobDisabled(job_id)),
            )

        if not force:
            if not self._is_due(registration, health, started):
                self._metrics.increment("skipped_not_due")
                return self._record(
                    registration, health, JobOutcome.SKIPPED_NOT_DUE, started, detail=""
                )

            if registration.idle_only:
                window = self._idle.is_idle(registration.scope)
                if not window.idle:
                    self._metrics.increment("skipped_not_idle")
                    return self._record(
                        registration,
                        health,
                        JobOutcome.SKIPPED_NOT_IDLE,
                        started,
                        detail=window.reason,
                    )

        self._metrics.increment("dispatches_attempted")
        handler = self._registry.handler_for(job_id)
        try:
            self._run_on_pool(registration, handler)
        except Exception as exc:  # noqa: BLE001 - see module docstring; nothing propagates
            self._metrics.increment("dispatches_failed")
            return self._record(
                registration,
                health,
                JobOutcome.FAILED,
                started,
                detail=f"{type(exc).__name__}: {exc}",
            )

        self._metrics.increment("dispatches_succeeded")
        return self._record(registration, health, JobOutcome.SUCCEEDED, started, detail="")

    def dispatch_due(self) -> tuple[JobRunResult, ...]:
        """One pass over every registered job. The scheduler's own tick.

        Every job is attempted independently: one failing, being disabled, or being skipped for
        a busy scope has no effect on the next. That independence is the whole reason this
        returns a tuple of results rather than stopping at the first problem.
        """
        return tuple(self.dispatch(job.job_id) for job in self._registry.all_jobs())

    # ---------------------------------------------------------------------- routing

    def _run_on_pool(self, registration: JobRegistration, handler: object) -> None:
        """§3's routing. The one place a job's declared class turns into a real substrate.

        A pool that was never wired in falls back to running inline rather than failing: a
        host that provided no process pool still gets its `CPU_PROCESS` jobs run, just without
        the isolation. Refusing instead would mean a misconfiguration silently stops
        maintenance work — the outcome §4.4 tells this package to avoid — and the fallback is
        visible in the type rather than hidden, since `thread_pool`/`process_pool` are
        constructor arguments a caller either passed or did not.
        """
        callable_handler: JobHandler = handler  # type: ignore[assignment]

        if registration.job_class is JobClass.ASYNC_IO:
            callable_handler()
            return

        pool = (
            self._thread_pool
            if registration.job_class is JobClass.NATIVE_THREAD
            else self._process_pool
        )
        if pool is None:
            callable_handler()
            return
        pool.submit(callable_handler).result(timeout=self._default_timeout)

    # ------------------------------------------------------------------ book-keeping

    def _is_due(
        self, registration: JobRegistration, health: JobHealth, now: datetime
    ) -> bool:
        """Event-triggered jobs are never due on a timer; that is what `None` means (§6.2).

        A job that has never run is due immediately — otherwise a freshly registered interval
        job would wait a full interval before its first run, which for a weekly job means the
        system does nothing about it for a week after deployment.
        """
        if registration.event_triggered:
            return False
        if health.last_run_at is None:
            return True
        return now - health.last_run_at >= timedelta(seconds=registration.interval_seconds or 0)

    def _record(
        self,
        registration: JobRegistration,
        health: JobHealth,
        outcome: JobOutcome,
        started: datetime,
        *,
        detail: str,
    ) -> JobRunResult:
        """Fold one dispatch into the job's health, tripping §10's guard if it is the fifth.

        A skip is not a failure and deliberately does not touch the consecutive-failure count:
        a job skipped for a busy scope every hour for a week has not failed once, and letting
        skips accumulate toward the guard would auto-disable the healthiest jobs on the busiest
        systems — precisely backwards.
        """
        finished = self._now()
        failed = outcome is JobOutcome.FAILED
        succeeded = outcome is JobOutcome.SUCCEEDED
        ran = failed or succeeded

        consecutive = health.consecutive_failures
        if failed:
            consecutive += 1
        elif succeeded:
            consecutive = 0

        tripped = failed and consecutive >= MAX_CONSECUTIVE_FAILURES and not health.disabled
        disabled_at = health.disabled_at
        disabled_reason = health.disabled_reason
        if tripped:
            disabled_at = finished
            disabled_reason = (
                f"auto-disabled after {consecutive} consecutive failures; "
                f"last error: {detail}"
            )
            self._metrics.increment("jobs_auto_disabled")

        updated = JobHealth(
            job_id=registration.job_id,
            consecutive_failures=consecutive,
            total_runs=health.total_runs + (1 if ran else 0),
            total_failures=health.total_failures + (1 if failed else 0),
            last_run_at=finished if ran else health.last_run_at,
            last_outcome=outcome,
            last_error_detail=detail if failed else health.last_error_detail,
            disabled_at=disabled_at,
            disabled_reason=disabled_reason,
        )
        self._registry.record_health(updated)

        return JobRunResult(
            job_id=registration.job_id,
            outcome=outcome,
            started_at=started,
            finished_at=finished,
            error_detail=detail,
            tripped_failure_guard=tripped,
        )

    # -------------------------------------------------------------------- §4.1 view

    def next_due(self) -> tuple[NextDueEstimate, ...]:
        """§4.1's operator-facing "which timer job fires next, and in how long".

        Best-effort by construction, and the contract says so: the real fire time also depends
        on `idle_only` conditions and on the job's own finder returning actual work. V2 had
        this and it was genuinely useful transparency — background work being an opaque black
        box is the thing worth avoiding, not the estimate being imprecise.
        """
        now = self._now()
        estimates: list[NextDueEstimate] = []
        for registration in self._registry.all_jobs():
            if registration.event_triggered:
                continue
            health = self._registry.health(registration.job_id)
            if health.disabled:
                continue
            interval = timedelta(seconds=registration.interval_seconds or 0)
            due_at = (health.last_run_at + interval) if health.last_run_at else now
            blocked = False
            if registration.idle_only:
                blocked = not self._idle.is_idle(registration.scope).idle
            estimates.append(
                NextDueEstimate(
                    job_id=registration.job_id,
                    seconds_until_due=max(0.0, (due_at - now).total_seconds()),
                    blocked_by_idle=blocked,
                )
            )
        return tuple(sorted(estimates, key=lambda e: e.seconds_until_due))


__all__ = ["GLOBAL_SCOPE", "JobHandler", "JobScheduler", "UnknownJob"]

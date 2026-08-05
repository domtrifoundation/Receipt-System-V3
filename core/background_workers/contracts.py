"""Background Workers data contracts (`v3-deepdive-12-background-workers-api.md` §2–§4, §10).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). It is the only file in this
package that anything outside `core/background_workers/` imports from.

Three things here are load-bearing rather than stylistic:

* **`JobClass` is declared by the registering API, never inferred here.** §3 makes routing a
  design requirement rather than a detail: an I/O-bound job on a process pool pays a pickling
  round trip for nothing, and a CPU-bound pure-Python job on the event loop blocks every other
  job behind it. This API cannot know which a domain job is; the domain API declares it.
* **`idle_only` and `scope` are two separate fields, not one.** §10 resolves the distinction
  explicitly: a per-user job checks *that user's* idle state, because one user's active session
  has no business blocking another user's unrelated maintenance; a genuinely system-wide job
  checks nobody's, because it touches no per-user resource. Collapsing them into a single
  boolean would force one of those two cases to be wrong.
* **`JobHealth.consecutive_failures` exists because §10 resolved the retry guard.** A
  permanently-failing job that retries forever is V2's own known failure mode. After
  `MAX_CONSECUTIVE_FAILURES` the job auto-disables and surfaces at `ATTENTION` — and
  re-enabling is an explicit staff action, never automatic, which is why `disabled_at` and
  `disabled_reason` are recorded rather than the counter simply being reset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from common.frozen_dict import FrozenDict

#: §10's resolved retry guard. Five consecutive failures auto-disables a job rather than
#: retrying into the void. Not configurable per job on purpose: a job that argued for a
#: higher ceiling would be a job whose owner should be fixing it instead.
MAX_CONSECUTIVE_FAILURES: int = 5

#: §10's locked-in starting cadences for §6.4's newly-designed jobs. Reasoned placeholders
#: that real operational data can tune later — named here so they are visible in one place
#: rather than buried per registration. `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1.
DEFAULT_CADENCE_SECONDS: FrozenDict = FrozenDict(
    {
        "expired_session_cleanup": 24 * 60 * 60,
        "break_glass_grant_sweep": 24 * 60 * 60,
        "account_deletion_grace_sweep": 24 * 60 * 60,
        "blob_backup_spot_verification": 7 * 24 * 60 * 60,
    }
)

#: The scope string meaning "this job touches no per-user resource" (§10). A real user id
#: anywhere else in this package means the opposite, so the sentinel is a value no user id
#: can collide with rather than `None`, which would read as "not set yet".
GLOBAL_SCOPE: str = "global"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobClass(str, Enum):
    """How a registered job must be dispatched (§3).

    The three map onto the three real execution substrates this project already uses across
    OCR, Preprocessing and Execution Core — the point of naming them here is that Background
    Workers applies that routing *generically*, for any domain API's job, instead of each API
    hand-rolling its own dispatch.

    Values are stable wire strings. Adding a member is fine; renaming or reusing a value is a
    breaking change to anything persisting a registration.
    """

    ASYNC_IO = "async_io"
    NATIVE_THREAD = "native_thread"
    CPU_PROCESS = "cpu_process"


class JobOutcome(str, Enum):
    """What one dispatch of a job produced.

    `SKIPPED_NOT_IDLE` is deliberately distinct from `SKIPPED_DISABLED`. The first is the
    system working as designed — an idle-only job correctly yielding to foreground work (§4) —
    and the second means something is wrong that a human has to clear (§10). An operator
    reading a run log needs those to look different at a glance.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED_NOT_IDLE = "skipped_not_idle"
    SKIPPED_DISABLED = "skipped_disabled"
    SKIPPED_NOT_DUE = "skipped_not_due"


@dataclass(frozen=True)
class JobRegistration:
    """One domain API's registered job — §2's contract, plus the scope §10 resolved.

    `owning_api` is for observability and debugging, not enforcement (§2 says so directly):
    this API does not police which API may register what, because it does not own any of their
    business logic and has no basis to judge.

    `interval_seconds=None` means event-triggered rather than timer-based. §6.2 uses exactly
    this for Telemetrees' signal-compilation job, and notes the contract already supported it
    while nothing had used it yet.
    """

    job_id: str
    owning_api: str
    job_class: JobClass
    idle_only: bool = False
    interval_seconds: int | None = None
    #: `GLOBAL_SCOPE`, or a real user id for a per-user-scoped job (§10).
    scope: str = GLOBAL_SCOPE
    description: str = ""

    @property
    def event_triggered(self) -> bool:
        """No interval means nothing fires this on a timer; something else must (§6.2)."""
        return self.interval_seconds is None


@dataclass(frozen=True)
class JobHealth:
    """A registered job's own run history, and whether the §10 guard has tripped.

    Deliberately separate from `JobRegistration`: a registration is what a domain API declared
    once and does not change, while this is live state that changes on every dispatch. Folding
    them together would mean re-declaring a job's identity every time it ran.
    """

    job_id: str
    consecutive_failures: int = 0
    total_runs: int = 0
    total_failures: int = 0
    last_run_at: datetime | None = None
    last_outcome: JobOutcome | None = None
    last_error_detail: str = ""
    disabled_at: datetime | None = None
    disabled_reason: str = ""

    @property
    def disabled(self) -> bool:
        return self.disabled_at is not None


@dataclass(frozen=True)
class JobRunResult:
    """The outcome of one dispatch attempt.

    Errors are data (`docs/PRINCIPLES.md` §4.1): a job that raises is recorded as `FAILED`
    with its detail, never allowed to propagate into the scheduler loop. A scheduler that could
    be taken down by one bad job would take every *other* registered job down with it, which is
    the failure this API exists to make impossible.
    """

    job_id: str
    outcome: JobOutcome
    started_at: datetime
    finished_at: datetime
    error_detail: str = ""
    #: Whether this dispatch is what tripped §10's guard. Distinct from `outcome=FAILED`: only
    #: the fifth consecutive failure carries it, which is what makes it a usable trigger for
    #: the one `ATTENTION` entry rather than five.
    tripped_failure_guard: bool = False

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


@dataclass(frozen=True)
class IdleWindow:
    """The answer to "is the relevant scope quiet right now" (§4).

    `reason` is populated whether or not the system is idle. A scheduler skipping a job needs
    to be able to say *why* in one line — "3 open runs for user-1" rather than a bare False,
    which is the difference between an operator diagnosing a stalled sweep in seconds and
    reading source to find out what the check even consulted.
    """

    scope: str
    idle: bool
    checked_at: datetime = field(default_factory=utcnow)
    reason: str = ""


@dataclass(frozen=True)
class NextDueEstimate:
    """§4.1's operator-facing "which timer job fires next, and in how long".

    Explicitly best-effort, and the contract says so rather than leaving a caller to discover
    it: the real fire time also depends on `idle_only` conditions and on the job's own finder
    returning actual work. Preserved from V2 because it was a genuinely good piece of
    transparency, not because V2 had it.
    """

    job_id: str
    seconds_until_due: float
    approximate: bool = True
    blocked_by_idle: bool = False


@dataclass(frozen=True)
class BackgroundWorkersMetrics:
    """This API's own counters, snapshotted (`metrics.py`)."""

    jobs_registered: int = 0
    dispatches_attempted: int = 0
    dispatches_succeeded: int = 0
    dispatches_failed: int = 0
    skipped_not_idle: int = 0
    skipped_disabled: int = 0
    skipped_not_due: int = 0
    jobs_auto_disabled: int = 0
    idle_checks_unavailable: int = 0


__all__ = [
    "DEFAULT_CADENCE_SECONDS",
    "GLOBAL_SCOPE",
    "MAX_CONSECUTIVE_FAILURES",
    "BackgroundWorkersMetrics",
    "IdleWindow",
    "JobClass",
    "JobHealth",
    "JobOutcome",
    "JobRegistration",
    "JobRunResult",
    "NextDueEstimate",
    "utcnow",
]

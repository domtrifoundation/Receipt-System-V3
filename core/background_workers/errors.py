"""Background Workers error taxonomy.

Surfaced as `error_detail` on `JobRunResult` and as `error_code` on the registry's own result
types rather than raised across the API boundary (`docs/PRINCIPLES.md` §4.1).

**The posture here is unusually strict about one thing.** This API's whole purpose is to run
other people's code on a schedule, which means a registered job failing is not an exceptional
condition — it is the normal case this package is built to survive. So nothing a *job* does
may propagate: a job that raises, hangs, or returns nonsense becomes a `FAILED` result and the
scheduler continues to the next job. A scheduler that could be taken down by one bad job would
take every other registered job down with it, and the resulting silence — no sweeps, no
retention purges, no session cleanup — would be far worse than the one job's own failure.

The one place this package is *not* forgiving is §10's failure guard: after five consecutive
failures a job auto-disables and requires an explicit staff action to re-enable. That is
deliberate asymmetry. Retrying forever is how V2's own known failure mode worked, and a job
that has failed five times running is not going to succeed on the sixth without someone
looking at it.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class BackgroundWorkersError(Exception):
    """Base for everything this API raises internally, never across its boundary."""


class UnknownJob(BackgroundWorkersError):
    """A dispatch, enable or disable naming a `job_id` nothing has registered."""


class DuplicateJobRegistration(BackgroundWorkersError):
    """Two registrations claiming the same `job_id`.

    Rejected rather than last-one-wins: two domain APIs both believing they own a job id is a
    real bug, and silently keeping whichever registered second would make which job actually
    runs depend on import order.
    """


class JobDisabled(BackgroundWorkersError):
    """A dispatch of a job the §10 guard auto-disabled.

    Not an error in the scheduler's own loop — it resolves to `SKIPPED_DISABLED`, a normal
    outcome. This type exists for a direct, deliberate dispatch (an operator saying "run this
    now"), where silently doing nothing would be worse than saying why.
    """


class IdleCheckUnavailable(BackgroundWorkersError):
    """Execution Core could not be reached to answer whether the scope is idle (§4).

    Resolves to *not idle*, never to idle. This is the one genuinely conservative default in
    this package: an idle-only job exists specifically to yield to foreground work, so running
    one while unable to confirm the system is quiet defeats the entire point of the class.
    Skipping a maintenance sweep costs one interval; running a `CPU_PROCESS` sweep during a
    live batch costs the user's actual work.
    """


class InvalidJobRegistration(BackgroundWorkersError):
    """An empty `job_id`, an empty `owning_api`, or a non-positive `interval_seconds`.

    A zero or negative interval is rejected rather than clamped: it almost always means a unit
    mix-up (milliseconds passed where seconds were meant), and clamping would turn that into a
    job hammering the pool every tick instead of an error at registration.
    """


#: Stable wire codes. Field-only-append discipline: a code is added, never renamed, because a
#: caller may be matching on it.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        UnknownJob: "UNKNOWN_JOB",
        DuplicateJobRegistration: "DUPLICATE_JOB_REGISTRATION",
        JobDisabled: "JOB_DISABLED",
        IdleCheckUnavailable: "IDLE_CHECK_UNAVAILABLE",
        InvalidJobRegistration: "INVALID_JOB_REGISTRATION",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "UNKNOWN_JOB": "No job is registered under that id.",
        "DUPLICATE_JOB_REGISTRATION": "A job is already registered under that id.",
        "JOB_DISABLED": (
            "That job auto-disabled after repeated failures and needs a staff action to "
            "re-enable."
        ),
        "IDLE_CHECK_UNAVAILABLE": (
            "Could not determine whether the system is idle, so idle-only work was held back."
        ),
        "INVALID_JOB_REGISTRATION": "The job registration was malformed.",
        "INTERNAL": "An unmapped internal error.",
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped."""
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    return ERROR_SUMMARIES.get(code, ERROR_SUMMARIES["INTERNAL"])


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "BackgroundWorkersError",
    "DuplicateJobRegistration",
    "IdleCheckUnavailable",
    "InvalidJobRegistration",
    "JobDisabled",
    "UnknownJob",
    "code_for",
    "summary_for",
]

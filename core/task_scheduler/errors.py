"""Task Scheduler error taxonomy.

These are surfaced as `error_code`/`error_detail` on the result contracts in `contracts.py`
rather than raised across this API's boundary (`docs/PRINCIPLES.md` §4.1). They exist as real
types because the *internal* call path still benefits from telling them apart — a task
rejected because its action isn't on the allowlist and one rejected because its cron
expression is malformed are different mistakes a client-side form should surface differently.

Task Scheduler has no equivalent of Auth's raise-loudly carve-out. Every failure here degrades
to error data (`docs/PRINCIPLES.md` §4.4) — including a trigger provider that cannot register
a task, which is reported through `contracts.TriggerRegistrationResult` rather than raised, so
one unavailable provider never takes the whole scheduler down (this package's own stated
instance of the graceful-degradation default: "a trigger whose provider is unavailable is an
unavailable trigger, not a crashed scheduler").
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class TaskSchedulerError(Exception):
    """Base for everything this package raises internally, never across its boundary."""


class UnknownSchedulableAction(TaskSchedulerError):
    """`action` names something absent from `registry.py`'s curated allowlist (§4).

    Rejected at creation time, never accepted and left to fail unsafely later at dispatch —
    the deep-dive's own §9 testing hook, "confirms `action` values outside the registered
    allowlist are rejected at creation time, never silently accepted."
    """


class InvalidCronExpression(TaskSchedulerError):
    """A cron expression `cron.py` cannot parse — malformed, wrong field count, or a value
    outside its field's real range (a minute of 61, a month of 13).

    Rejected at the API boundary (§9's own cron-validation testing hook), never surfaced as a
    confusing failure the first time the scheduler tries to compute a next occurrence.
    """


class InvalidTaskRequest(TaskSchedulerError):
    """An empty `action`, an empty `cron_expression`, or `action_params` that is not a
    `Mapping` — malformed independent of whether the action or the cron expression is even
    valid on their own."""


class TaskNotFound(TaskSchedulerError):
    """An update, delete, or lookup naming a `task_id` this user has no row for."""


class TaskLimitExceeded(TaskSchedulerError):
    """§10's resolved open question: a tier-dependent cap on how many tasks one user may have
    enabled at once exists as a real, checkable mechanism. The specific numbers per tier are
    Billing's own call, not this document's (§10) — `registry.py`'s own cap is a plain
    integer a caller supplies, defaulting to no limit until Billing's tiers are wired in.
    """


class TriggerUnavailable(TaskSchedulerError):
    """A `ScheduleTrigger` provider could not register or deregister a task right now.

    Degrades that one trigger, never the caller's create/update/delete call
    (`docs/PRINCIPLES.md` §4.4) — the task row itself is still written; only the *live wake*
    mechanism for it might not be armed until the provider is available again.
    """


class RoleForbidden(TaskSchedulerError):
    """The resolved caller role does not permit this call at all (`service.py`'s own gRPC
    boundary, added alongside it) — this API's own opening line names it as "letting an
    owner/staff user configure their own recurring actions," and includes the case where no
    role could be resolved at all (`docs/PRINCIPLES.md` §4.2, fail closed). Not part of
    `contracts.py`'s original taxonomy because permission resolution is `service.py`'s own
    concern (this module's own docstring already says so, mirroring `core/audit/service.py`'s
    injected, fail-closed `role_resolver`), added the moment that servicer was actually built.
    """


#: Stable wire codes for the `.proto` surface's own `error_code` field (§7). Field-only-append
#: discipline applies here the same way it does to the `.proto`: a code is added, never
#: renamed, because a client may be matching on it.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        UnknownSchedulableAction: "UNKNOWN_SCHEDULABLE_ACTION",
        InvalidCronExpression: "INVALID_CRON_EXPRESSION",
        InvalidTaskRequest: "INVALID_TASK_REQUEST",
        TaskNotFound: "TASK_NOT_FOUND",
        TaskLimitExceeded: "TASK_LIMIT_EXCEEDED",
        TriggerUnavailable: "TRIGGER_UNAVAILABLE",
        RoleForbidden: "ROLE_FORBIDDEN",
    }
)

#: Operator-facing one-liners, kept next to the codes so a client that only has the code
#: still has something to show (`docs/PRINCIPLES.md` §2.1.1 — a module-level lookup table
#: nothing should ever write is a `FrozenDict`, not a plain `dict`).
ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "UNKNOWN_SCHEDULABLE_ACTION": (
            "that action is not on the registered, schedulable allowlist"
        ),
        "INVALID_CRON_EXPRESSION": "that cron expression could not be parsed",
        "INVALID_TASK_REQUEST": "the scheduled task request was malformed",
        "TASK_NOT_FOUND": "no scheduled task exists with that id for this user",
        "TASK_LIMIT_EXCEEDED": "this user's tier does not allow any more scheduled tasks",
        "TRIGGER_UNAVAILABLE": (
            "the task was saved, but its live wake mechanism could not be armed right now"
        ),
        "ROLE_FORBIDDEN": "the caller's resolved role does not permit scheduling tasks",
        "INTERNAL": "an unexpected internal error occurred",
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped.

    Unmapped is deliberately not an exception of its own: a caller receiving `INTERNAL` with
    a real detail string is strictly better off than one receiving a crash from the error
    path itself (the same posture `core/logs/errors.py`'s `code_for` takes).
    """
    return ERROR_CODES.get(type(exc), "INTERNAL")


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "InvalidCronExpression",
    "InvalidTaskRequest",
    "RoleForbidden",
    "TaskLimitExceeded",
    "TaskNotFound",
    "TaskSchedulerError",
    "TriggerUnavailable",
    "UnknownSchedulableAction",
    "code_for",
]

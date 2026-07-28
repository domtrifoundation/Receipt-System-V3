"""Task Scheduler data contracts (`v3-deepdive-39-task-scheduler.md` §3, §4, §5, §7).

This is the only module in this package other packages import from (`docs/PRINCIPLES.md`
§1.1). Types and result shapes only — no cron parsing, no SQL, no gRPC.

Every type is `@dataclass(frozen=True)` (`docs/PRINCIPLES.md` §2.1), and `action_params` is a
`FrozenDict` rather than a plain `dict`: a frozen dataclass with a plain `dict` field is only
*shallowly* immutable, and a `UserScheduledTask` crosses the gRPC boundary and is cached by
whichever trigger provider registered it. Any `isinstance` check against it must test
`collections.abc.Mapping`, never `dict` — the Python 3.15 builtin `frozendict` is not a
`dict` subclass.

**Errors are data at this boundary, never exceptions** (`docs/PRINCIPLES.md` §4.1). This
package has no equivalent of Auth's raise-loudly carve-out — a caller resolving a session and
finding it insufficient for this call is `service.py`'s own concern (mirroring
`core/audit/service.py`'s injected, fail-closed `role_resolver`, since this sub-API's own
deep-dive names no dedicated permission-gate module the way Groups' does); every mutating or
reading operation below returns a result carrying `error_code`/`error_detail`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    """Timezone-aware UTC. Cron evaluation compares this against `cron_expression` occurrences
    computed in `cron.py`; a naive value here would be the one thing that silently drifted by
    a UTC offset the moment a self-hosted install ran anywhere but UTC+0."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class UserScheduledTask:
    """One owner/staff user's own recurring action (deep-dive §3).

    `created_by` is a `user_id` — scoped per-user, never a system-wide setting, per the
    deep-dive's own comment on this field. `action` is a name that must already exist in
    `registry.py`'s allowlist at creation time (§4) — this type carries no opinion about
    whether that is still true later, which is `registry.py`'s job to (re-)check, not a fact
    this frozen snapshot could keep current on its own.
    """

    task_id: str
    created_by: str
    action: str
    action_params: FrozenDict
    cron_expression: str
    enabled: bool
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class SchedulableAction:
    """One entry in the curated allowlist (§4) — never a raw string some caller happens to
    read and dispatch on unsafely. `param_keys` is informational only (which keys this
    action's own domain logic actually reads out of `action_params`), not a validating
    schema — the same "this package does not own the action" boundary (§1) means it does not
    own that action's own parameter contract either."""

    name: str
    description: str
    param_keys: tuple[str, ...] = ()


# --------------------------------------------------------------------- results
# Errors are data at this API's boundary, never exceptions raised across it
# (`docs/PRINCIPLES.md` §4.1). Every result below carries `error_code`/`error_detail`; the
# error code strings themselves live in `errors.py`.


@dataclass(frozen=True)
class TaskResult:
    """The outcome of creating, updating, or fetching one `UserScheduledTask`."""

    ok: bool
    task: UserScheduledTask | None = None
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class DeleteTaskResult:
    ok: bool
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class TaskListResult:
    """`tasks` empty with `ok=True` is a real, ordinary "you have no scheduled tasks yet",
    not a failure — the same "empty is not an error" shape this project's other list results
    (`MembersListResult`, `LogQueryResult`) already use."""

    ok: bool
    tasks: tuple[UserScheduledTask, ...] = ()
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class SchedulableActionsResult:
    """What populates the Interface screen's own action picker (§6) — the allowlist itself,
    never a hand-maintained second copy of it in a client."""

    ok: bool
    actions: tuple[SchedulableAction, ...] = ()
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class TriggerRegistrationResult:
    """What a `ScheduleTrigger` provider hands back from registering or deregistering a task.

    `docs/PRINCIPLES.md` §4.4, applied to this package's own stated instance of it: "a trigger
    whose provider is unavailable is an unavailable trigger, not a crashed scheduler." A
    provider that cannot register (Supervisor's own wake mechanism not wired up yet, an OS
    without the native scheduler this build targets) reports that as `ok=False` with a code,
    never raises out of `triggers/base.py`'s own registry.
    """

    ok: bool
    trigger_name: str = ""
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class FireDecision:
    """§5/§10's misfire policy, made a checkable value rather than a side effect: whether a
    task is due *right now*, and what to check against next time either way.

    `missed=True` is the concrete case §10's own resolved open question describes — "waits
    for the next scheduled occurrence, never catches up immediately." It is not an error: a
    late wake-up (an extended sleep, an outage) simply loses that one occurrence rather than
    firing a backlog of catch-up runs the moment the instance is available again.
    """

    should_fire: bool
    next_check_after: datetime
    missed: bool = False


__all__ = [
    "DeleteTaskResult",
    "FireDecision",
    "SchedulableAction",
    "SchedulableActionsResult",
    "TaskListResult",
    "TaskResult",
    "TriggerRegistrationResult",
    "UserScheduledTask",
    "utcnow",
]

"""The curated schedulable-action allowlist — a hard safety requirement (§4).

**Only a specific, registered set of actions are exposed to this mechanism at all** — never
arbitrary code, never a raw cron-to-shell-command mapping. Each schedulable action registers
itself here explicitly, the same discipline `docs/templates/new_provider.md` already asks of
every other pluggable capability in this project (`docs/PRINCIPLES.md` §1.2), so the actual
allowlist is visible and reviewable in one place rather than implicit in whatever happens to
read `action` as a string and dispatch on it.

**This is a genuinely mutable internal registry** (`docs/PRINCIPLES.md` §2.1.1's own drawn
line): populated at startup by whichever Core APIs expose a schedulable action of their own
(Execution Core's full rescan, Export Framework's SLSP export), so it is a plain `dict`
behind a lock, not a `FrozenDict` — the same distinction `core/logs/sinks.py`'s own
`SinkRegistry` documents for itself.

**No other Core API is wired to register a real action yet in this build.** `default_registry()`
therefore starts empty, the same posture `core/health/resource_ledger.py` takes with Setup
API's not-yet-existing `HardwareProfileReader`: a Task Scheduler process running today rejects
every `action` at creation time as `UNKNOWN_SCHEDULABLE_ACTION`, which is the correct,
fail-safe behaviour rather than a placeholder that happens to accept something because no one
has registered anything real yet.
"""

from __future__ import annotations

import threading

from .contracts import SchedulableAction
from .errors import TaskLimitExceeded, UnknownSchedulableAction


class SchedulableActionRegistry:
    """The allowlist itself. Thread-safe, since registration can happen from whichever Core
    API's own startup sequence reaches this process first — this project targets
    free-threaded 3.14t, so a plain unguarded `dict` write here would be a real race, not a
    theoretical one (`docs/PRINCIPLES.md` §3.3.1)."""

    def __init__(self) -> None:
        self._actions: dict[str, SchedulableAction] = {}
        self._lock = threading.Lock()

    def register(self, action: SchedulableAction) -> None:
        with self._lock:
            self._actions[action.name] = action

    def is_allowed(self, name: str) -> bool:
        with self._lock:
            return name in self._actions

    def get(self, name: str) -> SchedulableAction | None:
        with self._lock:
            return self._actions.get(name)

    def require(self, name: str) -> SchedulableAction:
        """Raising form for the creation-time gate (§9's own allowlist-enforcement testing
        hook): reject at creation, never silently accept and fail unsafely later at
        dispatch."""
        action = self.get(name)
        if action is None:
            raise UnknownSchedulableAction(
                f"{name!r} is not on the registered, schedulable allowlist"
            )
        return action

    def list(self) -> tuple[SchedulableAction, ...]:
        with self._lock:
            return tuple(sorted(self._actions.values(), key=lambda a: a.name))


def default_registry() -> SchedulableActionRegistry:
    """The startup default. Empty — see the module docstring for why that is deliberate."""
    return SchedulableActionRegistry()


#: §10's resolved open question: a tier-dependent cap on enabled tasks per user is a real
#: mechanism, with the specific numbers left to Billing's own tier definitions rather than
#: guessed at here. `None` means "no cap" — today's only real value, since no tier system is
#: wired into this build yet; a real deployment supplies a concrete integer per user's tier.
DEFAULT_MAX_TASKS_PER_USER: int | None = None


def enforce_task_cap(current_count: int, limit: int | None) -> None:
    """Raise `TaskLimitExceeded` if creating one more task would exceed `limit`.

    A plain function rather than a method on the registry above: the cap is per-*user*
    (tier-dependent), while the allowlist above is global and process-wide — conflating the
    two into one class would blur a distinction that matters (`docs/PRINCIPLES.md` §1.5).
    """
    if limit is not None and current_count >= limit:
        raise TaskLimitExceeded(
            f"this user already has {current_count} scheduled task(s); the tier limit is "
            f"{limit}"
        )


__all__ = [
    "DEFAULT_MAX_TASKS_PER_USER",
    "SchedulableActionRegistry",
    "default_registry",
    "enforce_task_cap",
]

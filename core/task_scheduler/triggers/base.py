"""`ScheduleTrigger` — the Provider Registry for *what wakes a scheduled task's dispatch*
(`v3-deepdive-39-task-scheduler.md` §5).

**The bug this design corrects, stated once here rather than per-provider.** An earlier
version of this design assumed the dispatching service reads `UserScheduledTask` rows at its
own in-process interval check — but Supervisor's own sleep/wake capability means that service
could genuinely be *asleep* when a scheduled task comes due, and a sleeping process cannot run
its own polling loop to notice its own schedule. Fixed with a swappable registry
(`docs/PRINCIPLES.md` §1.2) of *wake* mechanisms, each behind the identical interface, so the
choice of which one arms a given task is a config/availability decision, never baked into a
single hardcoded polling loop.

**`ScheduleTrigger` implementations sit behind one small adapter each** (`docs/PRINCIPLES.md`
§1.3) — Supervisor's own wake RPC, an OS-native scheduler binary, an in-process timer — so a
new wake mechanism is a new file here, never a change scattered across callers.

**Graceful degradation is the point of `TriggerRegistry`, not an afterthought**
(`docs/PRINCIPLES.md` §4.4, and this package's own stated instance of it): "a trigger whose
provider is unavailable is an unavailable trigger, not a crashed scheduler." Registering a
task's wake mechanism against an unavailable provider degrades to
`TriggerRegistrationResult(ok=False, ...)` — the task row itself is still written by
`store.py`; only its live wake arming might be pending until the provider comes back.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from ..contracts import TriggerRegistrationResult, UserScheduledTask
from ..errors import TriggerUnavailable, code_for


@runtime_checkable
class ScheduleTrigger(Protocol):
    """One wake mechanism. `register_trigger`/`deregister_trigger` are the deep-dive's own
    §5 sketch verbatim; `name` and `is_available` are this file's own additions, needed to
    make §4.4's degradation posture something callable rather than only documented."""

    @property
    def name(self) -> str:
        """Stable identifier, used as the registry key and in `TriggerRegistrationResult`."""

    def is_available(self) -> bool:
        """Whether this provider can actually arm a wake right now. Checked before every
        `register_trigger`/`deregister_trigger` call — never assumed, since availability can
        change between one call and the next (Supervisor's own wake service restarting, an
        OS-native scheduler binary that was never installed)."""

    async def register_trigger(self, task: UserScheduledTask) -> None:
        """Arm a wake for `task`. Raises `TriggerUnavailable` (or lets a provider-specific
        failure propagate) if it cannot — `TriggerRegistry` is what turns that into result
        data, never this method itself, so a provider implementation stays a plain adapter."""

    async def deregister_trigger(self, task_id: str) -> None:
        """Disarm a previously-registered wake. Idempotent: deregistering a task that was
        never armed (or already deregistered) is not an error."""


class TriggerRegistry:
    """Holds every configured `ScheduleTrigger` provider and is the one place
    `register_trigger`/`deregister_trigger` failures become data instead of exceptions.

    A genuinely mutable internal registry populated at startup — a plain `dict`, not a
    `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent, and this is not a
    constant), the same shape `core/logs/sinks.py`'s own `SinkRegistry` uses.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ScheduleTrigger] = {}
        self._lock = threading.Lock()

    def register(self, provider: ScheduleTrigger) -> None:
        with self._lock:
            self._providers[provider.name] = provider

    def get(self, name: str) -> ScheduleTrigger | None:
        with self._lock:
            return self._providers.get(name)

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._providers))

    async def arm(self, trigger_name: str, task: UserScheduledTask) -> TriggerRegistrationResult:
        """Register `task` with the named provider. Never raises — an unknown provider, an
        unavailable one, and one that raises while registering all collapse to the identical
        `ok=False` shape (`docs/PRINCIPLES.md` §4.4)."""
        provider = self.get(trigger_name)
        if provider is None:
            exc = TriggerUnavailable(f"no trigger provider registered as {trigger_name!r}")
            return TriggerRegistrationResult(
                ok=False, trigger_name=trigger_name, error_code=code_for(exc),
                error_detail=str(exc),
            )
        if not provider.is_available():
            exc = TriggerUnavailable(f"trigger provider {trigger_name!r} is not available")
            return TriggerRegistrationResult(
                ok=False, trigger_name=trigger_name, error_code=code_for(exc),
                error_detail=str(exc),
            )
        try:
            await provider.register_trigger(task)
        except Exception as exc:  # noqa: BLE001 - any provider failure degrades, never raises
            return TriggerRegistrationResult(
                ok=False, trigger_name=trigger_name, error_code=code_for(TriggerUnavailable()),
                error_detail=f"{type(exc).__name__}: {exc}",
            )
        return TriggerRegistrationResult(ok=True, trigger_name=trigger_name)

    async def disarm(self, trigger_name: str, task_id: str) -> TriggerRegistrationResult:
        provider = self.get(trigger_name)
        if provider is None:
            # Deregistering against a provider that no longer exists is not an error worth
            # surfacing — there is nothing left to disarm on this side either way.
            return TriggerRegistrationResult(ok=True, trigger_name=trigger_name)
        try:
            await provider.deregister_trigger(task_id)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            return TriggerRegistrationResult(
                ok=False, trigger_name=trigger_name, error_code=code_for(TriggerUnavailable()),
                error_detail=f"{type(exc).__name__}: {exc}",
            )
        return TriggerRegistrationResult(ok=True, trigger_name=trigger_name)


__all__ = ["ScheduleTrigger", "TriggerRegistry"]

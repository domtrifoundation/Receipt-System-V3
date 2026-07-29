"""`SupervisorWakeTrigger` — the correct default once a service can sleep (§5).

Delegates to Supervisor's own schedule-wake mechanism (its deep-dive §5.4, the same
lightweight always-resident timer that already wakes `SCHEDULED_ONLY`-class services like
Ingestion for its daily poll) rather than reinventing a second wake mechanism — the concrete
application of `docs/PRINCIPLES.md` §1.5 (shared substrate without conflating domains):
Supervisor already owns "wake a sleeping process at a specific time," and a second, competing
implementation of that here would be exactly the kind of reinvention that principle rules out.

**Supervisor does not exist as an implemented Core API yet in this build.** `SupervisorWakeClient`
is the one small adapter seam onto it (`docs/PRINCIPLES.md` §1.3) — a Protocol, not an import
of a package that is not there to import. With no client wired in, `is_available()` reports
`False` and every `register_trigger` call reports `TriggerUnavailable`
(`triggers/base.py`'s `TriggerRegistry.arm` turns that into `TriggerRegistrationResult(ok=False,
...)` rather than a raise) — the same fail-safe-until-wired-up posture
`core/health/resource_ledger.py` takes with Setup API's not-yet-existing `HardwareProfileReader`.
Wiring Supervisor in later means constructing this with a real client, not removing a
permissive default someone forgot about, because there is no permissive default here to
remove.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..contracts import UserScheduledTask, utcnow
from ..cron import next_after
from ..errors import TriggerUnavailable


@runtime_checkable
class SupervisorWakeClient(Protocol):
    """The seam onto Supervisor's own schedule-wake RPC (its deep-dive §5.4). Deliberately
    not an import of `core.supervisor` — that package does not exist in this build, and this
    Protocol is what keeps this trigger testable and constructible regardless."""

    async def schedule_wake(self, task_id: str, at) -> None:
        """Ask Supervisor to wake the dispatching service no later than `at` and reason about
        `task_id` when it does."""

    async def cancel_wake(self, task_id: str) -> None:
        """Cancel a previously scheduled wake. Idempotent — cancelling one that was never
        scheduled, or already fired, is not an error."""


class SupervisorWakeTrigger:
    """`client=None` (the default) is the honest "Supervisor is not wired up" state, not a
    stand-in that silently no-ops — see the module docstring for why that distinction is
    load-bearing here specifically."""

    def __init__(self, client: SupervisorWakeClient | None = None) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "supervisor_wake"

    def is_available(self) -> bool:
        return self._client is not None

    async def register_trigger(self, task: UserScheduledTask) -> None:
        if self._client is None:
            raise TriggerUnavailable(
                "no SupervisorWakeClient configured; Supervisor is not reachable"
            )
        next_time = next_after(task.cron_expression, utcnow())
        await self._client.schedule_wake(task.task_id, next_time)

    async def deregister_trigger(self, task_id: str) -> None:
        if self._client is None:
            # Nothing was ever armed on this side either — deregistering is a no-op, not a
            # failure, the same idempotence `SupervisorWakeClient.cancel_wake` itself states.
            return
        await self._client.cancel_wake(task_id)


__all__ = ["SupervisorWakeClient", "SupervisorWakeTrigger"]

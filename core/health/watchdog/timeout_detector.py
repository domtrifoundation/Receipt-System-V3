"""The silent-past-timeout check (`v3-deepdive-34-watchdog.md` §4).

Runs on its own interval, comparing each tracked instance's last kick against the timeout that
applies to it. **Watchdog's job stops at reporting.** Supervisor executes restarts, kept
deliberately separate so the thing deciding "should I restart this" is never the same code
path that might itself be hung (§1, §4).

There is no restart call in this file, and that absence is the guarantee — the same shape of
argument Audit's package makes about having no mutating result type.

§10's open question is resolved in `resolve_timeout` below: a global default with real
per-service overrides, because Inference's model-loading cycle is a genuinely different length
from a lightweight API's heartbeat, and neither one-size-fits-all nor per-service-mandatory
was the right answer.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from .contracts import Heartbeat, Liveness, SilenceReport, WatchdogConfig, WatchdogState
from .kicks import KickRegistry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_timeout(service: str, config: WatchdogConfig) -> int:
    """The timeout that applies to one service — §10's resolution.

    Reads the override map through `.get`, which works identically for a plain `dict` and for
    the 3.15 builtin `frozendict`. Nothing here does an `isinstance(x, dict)` check, which
    would silently miss the builtin because it is not a `dict` subclass
    (`docs/PRINCIPLES.md` §2.1).
    """
    override = config.per_service_timeouts.get(service)
    if isinstance(override, int) and override > 0:
        return override
    return config.timeout_seconds


def state_for(
    beat: Heartbeat | None,
    *,
    service: str,
    instance_id: str,
    config: WatchdogConfig,
    now: datetime,
) -> WatchdogState:
    """One instance's liveness as of `now`.

    An instance that has never kicked is `UNSEEN`, never `SILENT`. Restarting something that
    was never up would be Supervisor acting on a fiction, and a service still coming up during
    the boot sequence (`docs/PROCESS_TOPOLOGY.md` §6) is exactly the case that would hit.
    """
    timeout = resolve_timeout(service, config)
    if beat is None:
        return WatchdogState(
            service=service,
            instance_id=instance_id,
            liveness=Liveness.UNSEEN,
            last_kick_at=None,
            timeout_seconds=timeout,
        )
    silent_for = (now - beat.kicked_at).total_seconds()
    liveness = Liveness.SILENT if silent_for > timeout else Liveness.ALIVE
    return WatchdogState(
        service=service,
        instance_id=instance_id,
        liveness=liveness,
        last_kick_at=beat.kicked_at,
        version_commit=beat.version_commit,
        silent_for_seconds=max(0.0, silent_for),
        timeout_seconds=timeout,
    )


class TimeoutDetector:
    """Compares every tracked instance's last kick against its timeout (§4)."""

    def __init__(
        self,
        registry: KickRegistry,
        *,
        config: WatchdogConfig | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._registry = registry
        self._config = config or WatchdogConfig()
        self._now = now

    def check_for_silence(self) -> SilenceReport:
        """Every tracked instance's state, including the ones that are fine.

        §4's own signature returns only the silent services, and `SilenceReport.silent_services`
        preserves exactly that. The full state set is returned alongside it because the fleet
        screen (Interface's own deep-dive) renders every instance, and having it re-derive
        liveness from raw heartbeats would be a second opinion about the same question.
        """
        now = self._now()
        states = tuple(
            state_for(
                beat,
                service=beat.service,
                instance_id=beat.instance_id,
                config=self._config,
                now=now,
            )
            for beat in self._registry.all_kicks()
        )
        return SilenceReport(states=states, checked_at=now)

    def state(self, service: str, instance_id: str) -> WatchdogState:
        """One instance's state, `UNSEEN` if it has never kicked."""
        return state_for(
            self._registry.last_kick(service, instance_id),
            service=service,
            instance_id=instance_id,
            config=self._config,
            now=self._now(),
        )


__all__ = ["TimeoutDetector", "resolve_timeout", "state_for"]

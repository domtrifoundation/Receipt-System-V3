"""Watchdog kicks and config hot-reload (§9).

§9 asks for two things that look unrelated and are both about the same failure: a run that has
gone wrong while continuing to look fine from outside.

**Kicks happen at multiple points inside the loop, not only around it.** §9 says "start of each
cycle and throughout any idle wait — matching V2's own proven wiring, so a genuinely hung run is
caught, not just a hung idle loop." A process that kicks only between runs looks perfectly
healthy while wedged forever inside one; the kick has to be where the work is.

**A config change applies to the next run, and the reload counter is how anyone can tell.** §9
wants a support session to be able to confirm "yes, this run definitely picked up the config
change made five minutes ago" rather than assume it. The counter is the observable that makes
that a fact instead of an assumption — and applying changes at a run boundary rather than
mid-run means a run's own semantics never shift underneath it while receipts are in flight.

Kicking is failure-tolerant on purpose (`docs/PRINCIPLES.md` §4.4). Watchdog is a monitoring
dependency; a kick that cannot be delivered must not take down the run it was monitoring. The
inverse — failing the run because the health reporter is down — turns one degraded component
into an outage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import ExecutionConfig, WatchdogKicker

#: The service name this API registers under with Health's Watchdog. Constant rather than a
#: literal at each call site: three call sites with two spellings is two services, one of which
#: never kicks and is reported dead.
SERVICE_NAME: str = "execution_core"


@dataclass
class WatchdogHooks:
    """§9's kicks, counted so a test can prove where they happened.

    `kick_count` is not diagnostic decoration — §9's requirement is specifically that kicks
    happen *inside* the loop, and the only way to test "inside" rather than "at all" is to count
    them against the number of receipts processed.
    """

    kicker: WatchdogKicker | None = None
    instance_id: str = ""
    version_commit: str = ""
    kick_count: int = 0
    failed_kicks: int = 0

    def kick(self) -> None:
        """One heartbeat. Never raises — see this module's docstring."""
        if self.kicker is None:
            return
        try:
            self.kicker.kick(SERVICE_NAME, self.instance_id, self.version_commit)
        except Exception:  # noqa: BLE001 - a monitoring failure is not a run failure (§4.4)
            self.failed_kicks += 1
            return
        self.kick_count += 1


@dataclass
class ConfigReloader:
    """§9's hot reload, applied at run boundaries with an observable counter.

    `staged` versus `active` is the whole mechanism: a change lands in `staged` immediately and
    becomes `active` only when `apply_for_next_run()` is called between runs. A run that read
    `active` at its start therefore sees one consistent config for its whole lifetime, even if
    an owner edits the file halfway through a forty-receipt batch.
    """

    active: ExecutionConfig = field(default_factory=ExecutionConfig)
    reload_count: int = 0
    _staged: ExecutionConfig | None = None

    def stage(self, config: ExecutionConfig) -> None:
        """Record a new config without disturbing any run currently in flight."""
        self._staged = config

    @property
    def has_pending_reload(self) -> bool:
        return self._staged is not None

    def apply_for_next_run(self) -> ExecutionConfig:
        """Promote a staged config, if there is one, and return what the next run will use.

        Increments `reload_count` only when something actually changed hands. A counter that
        ticked on every run would answer "how many runs have there been", which is a question
        nobody needed and which makes the real question unanswerable.
        """
        if self._staged is not None:
            self.active = self._staged
            self._staged = None
            self.reload_count += 1
        return self.active


__all__ = ["ConfigReloader", "SERVICE_NAME", "WatchdogHooks"]

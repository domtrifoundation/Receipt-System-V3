"""Watchdog data contracts (`v3-deepdive-34-watchdog.md` §3, §4, §8).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). Watchdog is a sub-API with
its own boundary, so it has its own contracts rather than adding to the parent's — Health's
`contracts.py` is about status, the ledger and drift; this file is about the one binary
question "has this service gone silent".

`WatchdogConfig.per_service_timeouts` is a `FrozenDict` (§2.1). It is the resolution of §10's
open question — a global default plus real per-service overrides, because Inference's
model-loading cycle is genuinely a different length from Auth's heartbeat — and a config
object whose override map could be mutated after construction would make the timeout a service
is judged against depend on when you looked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from common.frozen_dict import FrozenDict

#: §8's defaults. Named here so `kicks.py` and `timeout_detector.py` cannot drift apart.
DEFAULT_KICK_INTERVAL_SECONDS: int = 15
DEFAULT_TIMEOUT_SECONDS: int = 60


class Liveness(str, Enum):
    """What Watchdog can say about a service instance.

    `SILENT` is the whole point: the process may well still exist and still pass a plain
    process-status check. `UNSEEN` is a name that has never kicked at all — a service that has
    not started yet is not the same thing as one that has stopped, and restarting something
    that was never up would be Supervisor acting on a fiction.

    Values are stable wire strings. Adding a member is fine; renaming or reusing a value is a
    breaking change to the `.proto` surface.
    """

    ALIVE = "ALIVE"
    SILENT = "SILENT"
    UNSEEN = "UNSEEN"


@dataclass(frozen=True)
class Heartbeat:
    """One kick, §3's contract verbatim in shape.

    `version_commit` rides *this*, not every business response (§5). Knowing which
    version/commit each running instance is on matters for diagnosing a channel-specific issue
    under A/B hot-swap, and the heartbeat is where that fact is cheap; paying for it on every
    real API call has no reason to happen just because it would also be cheap there.
    """

    service: str
    instance_id: str
    version_commit: str
    kicked_at: datetime


@dataclass(frozen=True)
class WatchdogState:
    """What Watchdog currently believes about one service instance (§4)."""

    service: str
    instance_id: str
    liveness: Liveness
    last_kick_at: datetime | None
    version_commit: str = ""
    silent_for_seconds: float = 0.0
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class SilenceReport:
    """What Watchdog hands Supervisor: the observation, never the action (§4).

    There is deliberately no `restart()` anywhere in this package, and no field here that
    could be read as an instruction. §1 draws that line explicitly — Watchdog detects and
    triggers, Supervisor acts, kept separate so the code deciding "should this be restarted"
    is never the same code path that might itself be hung.
    """

    states: tuple[WatchdogState, ...]
    checked_at: datetime

    @property
    def silent_services(self) -> tuple[str, ...]:
        """§4's `check_for_silence()` return, derived rather than stored twice."""
        return tuple(s.service for s in self.states if s.liveness is Liveness.SILENT)


@dataclass(frozen=True)
class WatchdogConfig:
    """§8's config, plus §10's resolved per-service override map.

    A single global timeout does not fit every service equally: Inference's model load is a
    genuinely different cycle length from a lightweight API's heartbeat. The resolution is a
    sensible global default plus an explicit override for the services that actually need one
    — not one-size-fits-all, and not forcing every service to configure its own value when
    most are fine with the default.
    """

    kick_interval_seconds: int = DEFAULT_KICK_INTERVAL_SECONDS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    per_service_timeouts: FrozenDict = field(default_factory=lambda: FrozenDict({}))


__all__ = [
    "DEFAULT_KICK_INTERVAL_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "Heartbeat",
    "Liveness",
    "SilenceReport",
    "WatchdogConfig",
    "WatchdogState",
]

"""The status layer: up/down, queue depth, dependency reachability (§1).

Services report *into* here; Health never reaches into a service to check on it. That is the
same inversion Watchdog's kick mechanism rests on (`v3-deepdive-34-watchdog.md` §3) and it is
what makes a hung-not-crashed process visible at all — a stuck process stops reporting even
though its OS-level status still reads "running".

Two decisions worth stating:

* **`UNKNOWN` is not `DOWN`.** Health reports; it does not decide (§1). A service whose last
  report has gone stale is `UNKNOWN` — "I could not tell" — and Supervisor's rollout gate is
  what turns that into a decision, not this module. Collapsing the two would quietly hand
  Health a policy role its own boundary section refuses.
* **Dependency reachability is a per-dependency fact, never one aggregate boolean.** An OCR
  process that cannot reach one cloud engine but has three local ones is `DEGRADED`, and an
  operator needs to know *which* dependency to have any chance of fixing it.

`docs/PRINCIPLES.md` §4.4 throughout: a probe that fails makes that dependency unreachable,
never the whole status report a failure.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone

from common.version import PROGRAM_VERSION

from .contracts import DependencyReachability, ServiceState, ServiceStatus
from .errors import UnknownService
from .metrics import HealthMetricsCollector

#: How long a report stays authoritative before the registry answers `UNKNOWN` instead.
#: Deliberately longer than Watchdog's own 60s kick timeout (§9): the two answer different
#: questions, and a status report going stale is a weaker signal than a service going silent.
DEFAULT_STATUS_STALENESS_SECONDS: int = 90


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StatusRegistry:
    """Every service instance's last known status, and how stale it is.

    One instance per Health process. Safe to call concurrently — the map is guarded by a real
    lock rather than relying on the GIL, since this project targets free-threaded 3.14t
    (`docs/PRINCIPLES.md` §3.3.1).
    """

    def __init__(
        self,
        *,
        staleness_seconds: int = DEFAULT_STATUS_STALENESS_SECONDS,
        metrics: HealthMetricsCollector | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._staleness = timedelta(seconds=staleness_seconds)
        self._metrics = metrics or HealthMetricsCollector()
        self._now = now
        self._lock = threading.Lock()
        self._statuses: dict[tuple[str, str], ServiceStatus] = {}

    def report(self, status: ServiceStatus) -> None:
        """Record a service instance's own report of itself."""
        with self._lock:
            self._statuses[(status.service, status.instance_id)] = status
        self._metrics.increment("status_reports_received")
        unreachable = sum(1 for d in status.dependencies if not d.reachable)
        if unreachable:
            self._metrics.increment("status_probes_unreachable", unreachable)

    def get(self, service: str, instance_id: str) -> ServiceStatus:
        """One instance's status, aged to `UNKNOWN` if its last report went stale.

        Raises `UnknownService` for a name that has never reported at all — a different fact
        from a name whose report is merely old, and one a caller genuinely wants to tell apart
        (a typo'd service name versus a service that died).
        """
        with self._lock:
            existing = self._statuses.get((service, instance_id))
        if existing is None:
            raise UnknownService(f"{service}/{instance_id}")
        return self._aged(existing, self._now())

    def instances(self, service: str) -> tuple[ServiceStatus, ...]:
        """Every known instance of one service, aged. Empty tuple if none have reported."""
        now = self._now()
        with self._lock:
            found = [s for (svc, _), s in self._statuses.items() if svc == service]
        return tuple(self._aged(s, now) for s in found)

    def all_statuses(self) -> tuple[ServiceStatus, ...]:
        now = self._now()
        with self._lock:
            found = list(self._statuses.values())
        return tuple(self._aged(s, now) for s in found)

    def _aged(self, status: ServiceStatus, now: datetime) -> ServiceStatus:
        """`UNKNOWN` once the report is older than the staleness window.

        The original `state` is deliberately not preserved in the returned record: a caller
        handed both a stale `UP` and a freshness flag will read the `UP`. `detail` carries the
        explanation, which is where an operator looks once the state itself says "unknown".
        """
        if now - status.reported_at <= self._staleness:
            return status
        age = int((now - status.reported_at).total_seconds())
        window = int(self._staleness.total_seconds())
        return ServiceStatus(
            service=status.service,
            instance_id=status.instance_id,
            state=ServiceState.UNKNOWN,
            version=status.version,
            version_commit=status.version_commit,
            reported_at=status.reported_at,
            queue_depth=status.queue_depth,
            dependencies=status.dependencies,
            resource_utilization=status.resource_utilization,
            detail=f"last report {age}s ago, past the {window}s window",
        )


def derive_state(
    dependencies: Sequence[DependencyReachability],
    *,
    running: bool = True,
    required: Sequence[str] = (),
) -> ServiceState:
    """The state a service should report about itself, given its dependency probes (§1).

    A service that is not running is `DOWN` regardless of anything else. A running service
    missing a dependency it *requires* is also `DOWN` — it cannot serve. A running service
    missing an optional dependency is `DEGRADED`, which is the whole reason that state exists
    (`docs/PRINCIPLES.md` §4.4): a missing OCR engine means that engine is unavailable, never
    a failed run, and reporting `DOWN` here would make Supervisor refuse a serviceable release.

    Lives here rather than in each service so there is one opinion about what `DEGRADED` means
    — the alternative is thirty processes each drawing the line slightly differently.
    """
    if not running:
        return ServiceState.DOWN
    unreachable = {d.name for d in dependencies if not d.reachable}
    if unreachable & set(required):
        return ServiceState.DOWN
    if unreachable:
        return ServiceState.DEGRADED
    return ServiceState.UP


def self_report(
    service: str,
    instance_id: str,
    *,
    dependencies: Sequence[DependencyReachability] = (),
    required: Sequence[str] = (),
    queue_depth: int = 0,
    version_commit: str = "",
    running: bool = True,
    now: Callable[[], datetime] = _utc_now,
) -> ServiceStatus:
    """Build the status a service reports about itself.

    `version` comes from `common/version.py`, never a literal restated per service:
    `docs/PROCESS_TOPOLOGY.md` §7 needs the running version on this record so Watchdog can
    report which version each instance is on, and a per-service copy of that string is exactly
    the drift that one constant exists to prevent.
    """
    return ServiceStatus(
        service=service,
        instance_id=instance_id,
        state=derive_state(dependencies, running=running, required=required),
        version=PROGRAM_VERSION,
        version_commit=version_commit,
        reported_at=now(),
        queue_depth=queue_depth,
        dependencies=tuple(dependencies),
    )


__all__ = [
    "DEFAULT_STATUS_STALENESS_SECONDS",
    "StatusRegistry",
    "derive_state",
    "self_report",
]

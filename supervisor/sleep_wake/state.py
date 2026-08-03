"""Live sleep state — which services are genuinely asleep right now, and when each was
last active. Not in the deep-dive's own §2 package layout, added because `GetSleepStatus`/
`ForceWake` need somewhere real to read/write this from; `classification.py` only answers
the static "what policy does this service have," never the live "is it asleep right now."

**In-memory, not persisted** — genuinely correct for this state's own nature: which
services are asleep is a fact about *this running Supervisor process's* own management of
its child processes, not something meaningful to reload from disk after a restart (a
fresh Supervisor process starts having launched nothing yet).
"""

from __future__ import annotations

import threading
from datetime import datetime

from ..contracts import ServiceState, SleepPolicy, SleepStatus, utcnow
from .classification import DEFAULT_IDLE_TIMEOUT_MINUTES, policy_for

__all__ = ["SleepStateStore"]


class SleepStateStore:
    """Thread-safe live tracking of one Supervisor process's own service states."""

    def __init__(self, *, idle_timeout_minutes: int = DEFAULT_IDLE_TIMEOUT_MINUTES) -> None:
        self._lock = threading.Lock()
        self._idle_timeout_minutes = idle_timeout_minutes
        self._state: dict[str, ServiceState] = {}
        self._last_activity: dict[str, datetime | None] = {}

    def mark_active(self, service_name: str) -> None:
        with self._lock:
            self._state[service_name] = ServiceState.RUNNING
            self._last_activity[service_name] = utcnow()

    def mark_sleeping(self, service_name: str) -> None:
        with self._lock:
            self._state[service_name] = ServiceState.SLEEPING

    def status_for(self, service_name: str) -> SleepStatus:
        with self._lock:
            state = self._state.get(service_name, ServiceState.STOPPED)
            last_activity = self._last_activity.get(service_name)
        return SleepStatus(
            service_name=service_name, policy=policy_for(service_name), state=state,
            last_activity_at=last_activity,
        )

    def is_idle_expired(self, service_name: str) -> bool:
        """Whether an `IDLE_TIMEOUT`-class service has been inactive long enough to be a
        real sleep candidate right now. `NEVER`/`SCHEDULED_ONLY` services are never
        idle-expired through this check — they sleep (or don't) on their own distinct
        triggers (§6.2), not a timeout."""
        if policy_for(service_name) is not SleepPolicy.IDLE_TIMEOUT:
            return False
        with self._lock:
            last_activity = self._last_activity.get(service_name)
        if last_activity is None:
            return False
        return (utcnow() - last_activity).total_seconds() >= self._idle_timeout_minutes * 60

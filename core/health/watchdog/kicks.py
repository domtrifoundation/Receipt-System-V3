"""Receiving and tracking heartbeats (`v3-deepdive-34-watchdog.md` §3).

The inversion this module rests on is the whole reason Watchdog can detect anything a process
table cannot: **a service proves its own liveness by calling in**, and Watchdog never reaches
into a service to check on it. A process that is stuck stops kicking while its OS-level status
still reads "running", which is precisely the hung-not-crashed failure §1 exists for.

Kicks are the highest-frequency operation in this sub-API (§6), so the store is a plain map
behind a real lock — not relying on the GIL, since this project targets free-threaded 3.14t
(`docs/PRINCIPLES.md` §3.3.1) — and nothing on the receive path does I/O.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone

from .contracts import Heartbeat
from .errors import InvalidHeartbeat


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KickRegistry:
    """The last heartbeat from every service instance that has ever kicked.

    Deliberately keyed by `(service, instance_id)` rather than by service alone. Under A/B
    hot-swap across channels (§5) two instances of one service genuinely run at once on
    different commits, and collapsing them would let a healthy new instance's kick vouch for a
    hung old one still holding real work.
    """

    def __init__(self, *, now: Callable[[], datetime] = _utc_now) -> None:
        self._now = now
        self._lock = threading.Lock()
        self._last: dict[tuple[str, str], Heartbeat] = {}

    def kick(self, service: str, instance_id: str, version_commit: str = "") -> Heartbeat:
        """Record a service instance proving it is alive (§3).

        Called periodically by every long-running service's own internal loop. Raises on a
        heartbeat that names no instance — internally, never across the boundary
        (`docs/PRINCIPLES.md` §4.1); `service.py` converts it to an error code.
        """
        if not service or not instance_id:
            raise InvalidHeartbeat(f"service={service!r} instance_id={instance_id!r}")
        beat = Heartbeat(
            service=service,
            instance_id=instance_id,
            version_commit=version_commit,
            kicked_at=self._now(),
        )
        with self._lock:
            self._last[(service, instance_id)] = beat
        return beat

    def last_kick(self, service: str, instance_id: str) -> Heartbeat | None:
        with self._lock:
            return self._last.get((service, instance_id))

    def all_kicks(self) -> tuple[Heartbeat, ...]:
        with self._lock:
            return tuple(self._last.values())

    def forget(self, service: str, instance_id: str) -> None:
        """Drop an instance Supervisor has confirmed is gone for good.

        Without this, a decommissioned instance stays permanently `SILENT` and keeps being
        reported — an alert that never clears is an alert that stops being read. Supervisor
        owns the decision that an instance is retired; this is the hook it calls.
        """
        with self._lock:
            self._last.pop((service, instance_id), None)


__all__ = ["KickRegistry"]

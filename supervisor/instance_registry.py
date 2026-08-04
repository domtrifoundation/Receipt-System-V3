"""Tracks every currently-running `(service_name, version)` instance — the real state
multi-version-concurrent service serving needs and single-service-per-name boot never had
to. In-memory, scoped to one Supervisor process's own lifetime (the same scope
`sleep_wake/state.py`'s own `SleepStateStore` already uses for live process state, never
persisted — a restarted Supervisor re-derives this by nothing being "running" until it
actually launches something again, same posture as every other live-only tracker here).
"""

from __future__ import annotations

import threading

from .contracts import ServiceLaunchResult

__all__ = ["InstanceRegistry"]


def _key(service_name: str, version: str) -> tuple[str, str]:
    return (service_name, version)


class InstanceRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[tuple[str, str], ServiceLaunchResult] = {}

    def get(self, service_name: str, version: str) -> ServiceLaunchResult | None:
        with self._lock:
            return self._running.get(_key(service_name, version))

    def record(self, service_name: str, version: str, result: ServiceLaunchResult) -> None:
        with self._lock:
            self._running[_key(service_name, version)] = result

    def forget(self, service_name: str, version: str) -> None:
        with self._lock:
            self._running.pop(_key(service_name, version), None)

    def all_for_service(self, service_name: str) -> tuple[tuple[str, ServiceLaunchResult], ...]:
        """Every `(version, result)` currently tracked as running for `service_name` —
        real A/B coexistence, checkable directly: a pin/launch on one version never
        appears against another version of the same service."""
        with self._lock:
            return tuple(
                (version, result) for (name, version), result in self._running.items() if name == service_name
            )

    def all(self) -> tuple[tuple[str, str, ServiceLaunchResult], ...]:
        with self._lock:
            return tuple((name, version, result) for (name, version), result in self._running.items())

    def all_pids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(r.pid for r in self._running.values() if r.pid is not None)

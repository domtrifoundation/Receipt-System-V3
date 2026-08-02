"""Operational counters and timings for Auth (deep-dive §8.3).

This API is I/O-bound end to end, so the signal worth collecting is not GIL contention or
CPU profiles — it is round-trip latency per authentication method and session-lookup latency
under load. Those are Health API's live-diagnostic territory; this module is the in-process
collection point Health reads from, not a second monitoring system.

**Nothing here records an identity.** Counters are keyed by method and outcome, never by
user id, email, phone number, session id, or IdP subject. A metrics surface that quietly
becomes a login-history log for anyone who can read process state is a real, avoidable
privacy failure, and the constraint is cheap to hold from the start.

**Thread-safety is explicit, not assumed.** These counters are read and written from the
gRPC thread pool and from `in_thread` workers, and this project targets free-threading
builds where no GIL serializes a `+=` on a shared dict entry (`docs/PRINCIPLES.md` §3.3.1).
The lock is what makes the increments correct there, not an artefact of caution.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass
class _Timing:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0

    def observe(self, elapsed_ms: float) -> None:
        self.count += 1
        self.total_ms += elapsed_ms
        self.max_ms = max(self.max_ms, elapsed_ms)

    @property
    def mean_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0


class AuthMetrics:
    """A genuinely mutable internal registry — a plain `dict`, not a `FrozenDict`.

    `docs/PRINCIPLES.md` §2.1.1 draws that line by intent: constants are frozen, live
    counters are not, and the type is where the difference has to be visible.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._timings: dict[str, _Timing] = {}

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def observe(self, name: str, elapsed_ms: float) -> None:
        with self._lock:
            self._timings.setdefault(name, _Timing()).observe(elapsed_ms)

    def timer(self, name: str) -> _Stopwatch:
        return _Stopwatch(self, name)

    def snapshot(self) -> Mapping[str, object]:
        """A point-in-time copy for Health API. Plain nested mappings, deliberately not the
        live structures — a consumer holding a reference to those could observe a half-
        applied update."""
        with self._lock:
            counters = dict(self._counters)
            timings = {
                name: {"count": t.count, "mean_ms": t.mean_ms, "max_ms": t.max_ms}
                for name, t in self._timings.items()
            }
        return {"counters": counters, "timings": timings}


@dataclass
class _Stopwatch:
    metrics: AuthMetrics
    name: str
    _start: float = field(default=0.0, repr=False)

    def __enter__(self) -> _Stopwatch:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.metrics.observe(self.name, (time.perf_counter() - self._start) * 1000.0)


#: Names used by `service.py`. Collected here so the set stays enumerable rather than being
#: discovered by grepping for string literals across the package.
LOGIN_INITIATED = "auth.login.initiated"
LOGIN_SUCCEEDED = "auth.login.succeeded"
LOGIN_FAILED = "auth.login.failed"
SECOND_FACTOR_REQUIRED = "auth.login.second_factor_required"
SESSION_VALIDATED = "auth.session.validated"
SESSION_REJECTED = "auth.session.rejected"
SESSION_REVOKED = "auth.session.revoked"
STEP_UP_ISSUED = "auth.step_up.issued"
BREAK_GLASS_GRANTED = "auth.break_glass.granted"
BREAK_GLASS_CHECKED = "auth.break_glass.checked"
VALIDATE_LATENCY = "auth.session.validate_ms"
LOGIN_LATENCY = "auth.login.round_trip_ms"

__all__ = [
    "BREAK_GLASS_CHECKED", "BREAK_GLASS_GRANTED", "LOGIN_FAILED", "LOGIN_INITIATED",
    "LOGIN_LATENCY", "LOGIN_SUCCEEDED", "SECOND_FACTOR_REQUIRED", "SESSION_REJECTED",
    "SESSION_REVOKED", "SESSION_VALIDATED", "STEP_UP_ISSUED", "VALIDATE_LATENCY",
    "AuthMetrics",
]

"""Counters for this API's own behaviour, and the immutable snapshot of them.

Same split `core/health/metrics.py` and `core/audit/metrics.py` both use: a genuinely mutable
`dict` behind a lock (`docs/PRINCIPLES.md` §2.1.1 draws the immutability line at intent, and
a live counter table is not a constant), handing out `contracts.AccountGuardianMetrics`, a
frozen contract, so a caller can never hold a view that mutates under it mid-read.

This API has no hot path of its own to speak of (deep-dive §8.1) — volume here is
self-service account actions, not per-request traffic — so these counters exist for the same
reason Audit's do: shape-of-activity visibility for Health/Telemetrees, not latency
instrumentation.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import AccountGuardianMetrics

#: Derived from the contract itself so the two cannot drift apart — adding a counter means
#: adding a field to `AccountGuardianMetrics` and nothing else.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(AccountGuardianMetrics))


class AccountGuardianMetricsCollector:
    """Thread-safe counters. One instance per Account Guardian process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising — instrumentation must never be
        able to fail the privileged action it is counting."""
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> AccountGuardianMetrics:
        with self._lock:
            counts = dict(self._counts)
        return AccountGuardianMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "AccountGuardianMetricsCollector"]

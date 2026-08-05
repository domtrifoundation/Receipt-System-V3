"""Counters for this API's own behaviour, and the immutable snapshot of them.

Matches `core/logs/metrics.py`'s own shape exactly: the counter names are derived from the
`ContentSecurityMetrics` contract itself so the two cannot drift apart, the counters are a
genuinely mutable internal structure guarded by a real lock (not relying on the GIL making
`+=` atomic — this project targets free-threaded 3.14t, §3.3.1), and the snapshot handed out
is the frozen contract, never the live counters.

What makes this API's own metrics worth having, specifically: Health and Telemetrees cannot
infer "how many files were denied because every provider was unavailable" versus "how many
were denied because scanners disagreed" from anything else this API produces — a `ScanVerdict`
is a per-file answer, and only these counters answer "is this installation's scanning coverage
actually healthy over time."
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import ContentSecurityMetrics

#: Derived from the contract itself — adding a counter means adding a field to
#: `ContentSecurityMetrics` and nothing else.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(ContentSecurityMetrics))


class ContentSecurityMetricsCollector:
    """Thread-safe counters. One instance per Content Security process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        A metrics call is instrumentation on a path whose own correctness must never depend
        on it — a typo'd counter name must not be what turns a real scan verdict into an
        unhandled exception on its way out.
        """
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> ContentSecurityMetrics:
        with self._lock:
            counts = dict(self._counts)
        return ContentSecurityMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "ContentSecurityMetricsCollector"]

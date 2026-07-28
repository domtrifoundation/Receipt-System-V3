"""Counters this API exposes to Health API's own resource ledger.

Deliberately counters and gauges only — no timings, no payloads, nothing that would make
this a second, weaker Logs. Health owns the live ledger; this module just holds the numbers
Persistence itself is the only one able to observe.

The counter map is a genuinely mutable internal registry, so it is a plain `dict`. The
*names* table is a module-level constant, so it is a `FrozenDict` (`docs/PRINCIPLES.md`
§2.1.1). The distinction is intent and it is visible in the types.
"""

from __future__ import annotations

import threading

from common.frozen_dict import FrozenDict

#: Every metric this API emits, with what it means. A constant lookup table.
METRIC_DESCRIPTIONS = FrozenDict(
    {
        "blob_writes": "Local blob writes that completed.",
        "blob_dedup_hits": "Writes satisfied by an existing logical_id — one blob, two refs.",
        "blob_backup_confirmed": "Blob writes at least one target confirmed (durable).",
        "blob_backup_full": "Blob writes every enabled target confirmed (fully synced).",
        "blob_backup_failed": "Per-target upload failures, summed across targets.",
        "canonical_writes": "Receipt writes committed with their Historian event.",
        "historian_data_events": "Data-change events appended.",
        "historian_narrative_events": "Narrative events appended.",
        "exports_generated": "Export provider calls that produced an artifact.",
        "reimport_conflicts": "Field conflicts surfaced for human resolution.",
        "archive_sync_mirrored": "Blobs mirrored to an external target.",
        "archive_sync_paused": "Times a mirror paused on an unreachable target.",
        "verify_hash_mismatches": "Blobs whose content did not match their physical_hash.",
    }
)


class Metrics:
    """Thread-safe counters.

    The lock is explicit rather than relying on the GIL making `+=` atomic — it is not, and
    on a free-threaded build the assumption would be plainly wrong (`docs/PRINCIPLES.md`
    §3.3.1). Persistence's work is I/O-bound so free-threading relevance here is genuinely
    low, but "low relevance" is not "safe to assume the GIL is serializing this."
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {name: 0 for name in METRIC_DESCRIPTIONS}

    def increment(self, name: str, by: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + by

    def snapshot(self) -> FrozenDict:
        """An immutable point-in-time copy — a caller can never mutate the live counters."""
        with self._lock:
            return FrozenDict(dict(self._counters))

    def reset(self) -> None:
        with self._lock:
            self._counters = {name: 0 for name in METRIC_DESCRIPTIONS}


__all__ = ["METRIC_DESCRIPTIONS", "Metrics"]

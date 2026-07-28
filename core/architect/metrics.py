"""Architect's own counters (`v3-deepdive-26-architect-api.md` §2).

Deliberately small and deliberately about *this API's* health, not about the data it
holds. "How many corporations exist" is a directory query; "how many contributions were
rejected at prescreen" is a fact about the pipeline, and only the second kind belongs here.

The counters that matter most are the refusals — `prescreen_unavailable`,
`merge_refused_no_approval`, `alias_conflicts` — because each one records a gate doing its
job, and a sudden change in any of them is the earliest visible sign that something
upstream started behaving differently.

`ArchitectMetrics` is a mutable collector on purpose (a counter table is not a constant,
`docs/PRINCIPLES.md` §2.1.1's own carve-out); `snapshot()` is the frozen contract that
crosses a boundary, with a `FrozenDict` payload so a reader cannot edit the numbers it was
handed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from common.frozen_dict import FrozenDict

from .temporal_learning.contracts import utcnow

#: Every counter this API keeps, with what it means. Iterated to initialize the collector,
#: so a counter cannot exist without a stated meaning. `FrozenDict` — module-level
#: constant lookup table, §2.1.1.
COUNTER_DESCRIPTIONS = FrozenDict(
    {
        "definitions_registered": "definitions accepted into the registry",
        "definitions_rejected": "registrations refused as duplicate or malformed",
        "definition_lookups": "resolved definition reads",
        "definition_misses": "lookups for a code that is not registered",
        "identifier_validations_failed": "reference-identifier values failing their structure",
        "entities_created_local": "entities created directly in the local layer",
        "entities_shared": "explicit share actions taken (the §3.1 consent gate)",
        "contributions_submitted": "contributions entering the moderation queue",
        "contributions_approved": "contributions a staff member approved",
        "contributions_rejected": "contributions rejected at prescreen or by staff",
        "contributions_merged": "contributions landed in the global layer",
        "prescreen_unavailable": "prescreen runs where no provider could form a verdict",
        "merge_refused_no_approval": "merge attempts refused for missing approval",
        "merge_refused_no_prescreen": "merge attempts refused for missing prescreen",
        "curation_candidates_staged": "cleanup candidates staged for review",
        "alias_conflicts": "alias registrations refused as a genuine conflict",
        "seed_records_fetched": "records returned by vendor seed sources",
        "seed_sources_degraded": "seed-source runs that contributed nothing",
    }
)


@dataclass(frozen=True)
class MetricsSnapshot:
    """An immutable point-in-time reading, safe to hand across a process boundary."""

    counters: FrozenDict
    taken_at: datetime = field(default_factory=utcnow)

    def get(self, name: str) -> int:
        return int(self.counters.get(name, 0))


class ArchitectMetrics:
    """The live collector. Plain dict: a counter table is genuinely mutable state."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {name: 0 for name in COUNTER_DESCRIPTIONS}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are accepted rather than raising.

        Metrics collection failing a call path it only observes would be a strictly worse
        outcome than an unlabelled counter (`docs/PRINCIPLES.md` §4.4) — and the unknown
        name showing up in a snapshot is itself the signal that something needs a
        description added above.
        """
        self._counters[name] = self._counters.get(name, 0) + amount

    def get(self, name: str) -> int:
        return self._counters.get(name, 0)

    def snapshot(self) -> MetricsSnapshot:
        return MetricsSnapshot(counters=FrozenDict(dict(self._counters)))

    def reset(self) -> None:
        """For a test or a fresh collection window. Never called on the live path."""
        self._counters = {name: 0 for name in COUNTER_DESCRIPTIONS}


__all__ = ["COUNTER_DESCRIPTIONS", "ArchitectMetrics", "MetricsSnapshot"]

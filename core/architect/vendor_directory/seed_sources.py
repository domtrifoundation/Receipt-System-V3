"""The vendor seed-source Provider Registry (`docs/PRINCIPLES.md` §1.2).

**Not listed in the deep-dive's own §2 package layout**, added because §3's Wikidata
bootstrap is explicitly one source with real, stated limits (name and category only, and
an entry count nobody has verified against the live endpoint yet). A capability with known
coverage gaps is exactly the case where "one provider chosen by config" is the wrong
shape: several sources contributing in the same run corroborate each other, and a source
being unreachable costs that source's contribution rather than the run.

Every seeded record still enters the directory through temporal_learning's own moderation
pipeline. A Wikidata-sourced entry is not privileged over a system-learned one
(deep-dive §3.2) — this registry produces *candidates*, never directory contents.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from ..contracts import BootstrapResult, SparqlFilter, VendorSeedRecord


class VendorSeedSource(Protocol):
    """A source of candidate vendor records.

    `is_available()` is separate from `fetch()` on purpose: a caller wants to be able to
    report "this source is not configured" to an operator without provoking a network
    attempt to find that out.
    """

    name: str

    def is_available(self) -> bool: ...

    async def fetch(self, query_filter: SparqlFilter | None = None) -> BootstrapResult: ...


class SeedSourceRegistry:
    """Holds the enabled sources and runs them together.

    `_sources` is a genuinely mutable internal registry populated at startup, so it is a
    plain `dict` — `docs/PRINCIPLES.md` §2.1.1's `FrozenDict` rule is about module-level
    constants, and keeping the distinction visible in the type is the point of that rule's
    own carve-out.
    """

    def __init__(self, sources: tuple[VendorSeedSource, ...] = ()) -> None:
        self._sources: dict[str, VendorSeedSource] = {s.name: s for s in sources}

    def register(self, source: VendorSeedSource) -> None:
        self._sources[source.name] = source

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._sources))

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(n for n, s in self._sources.items() if s.is_available()))

    async def fetch_all(
        self, query_filter: SparqlFilter | None = None
    ) -> tuple[BootstrapResult, ...]:
        """Run every registered source concurrently and return one result each.

        Results are returned per-source rather than merged so an operator can see which
        source produced what, and so a source that degraded is visibly distinct from one
        that genuinely found nothing. `return_exceptions=True` because a source raising
        despite its own contract must not take the sibling sources' results down with it.
        """
        if not self._sources:
            return ()
        ordered = [self._sources[name] for name in sorted(self._sources)]
        gathered = await asyncio.gather(
            *(s.fetch(query_filter) for s in ordered), return_exceptions=True
        )
        out: list[BootstrapResult] = []
        for source, result in zip(ordered, gathered, strict=True):
            if isinstance(result, BaseException):
                out.append(
                    BootstrapResult(
                        source=source.name,
                        degraded_reason=f"source raised: {result}",
                    )
                )
            else:
                out.append(result)
        return tuple(out)


def merge_seed_records(
    results: tuple[BootstrapResult, ...],
) -> tuple[VendorSeedRecord, ...]:
    """Flatten several sources' records, de-duplicating on `(source, external_id)`.

    Deliberately *not* de-duplicated across sources by name: two sources naming the same
    business is corroboration, and collapsing that here would throw away the signal the
    parallel-provider shape exists to produce. Whatever consumes this decides what to do
    with agreement; this function only stops one source's own duplicate rows.
    """
    seen: set[tuple[str, str]] = set()
    out: list[VendorSeedRecord] = []
    for result in results:
        for record in result.records:
            key = (record.source, record.external_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(record)
    return tuple(out)


__all__ = ["SeedSourceRegistry", "VendorSeedSource", "merge_seed_records"]

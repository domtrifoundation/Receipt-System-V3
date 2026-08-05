"""The polling pass: which poller answers which fact kind, and what changed (§3, §5, §8).

This module holds `PollerRegistry` — the Provider Registry (`docs/PRINCIPLES.md` §1.2) mapping
a `TrackedFactKind` to the mechanism that can actually answer it — and `WardenPoller`, which
runs one pass over every tracked dependency and reports what moved.

Two properties shape the whole file:

**A pass never fails.** An unreachable PyPI or a rate-limited GitHub costs one fact one cycle
and is recorded in `PollResult.unreachable`; every other dependency is still polled. Monitoring
that stopped at the first unreachable source would silently take every other dependency's
tracking down with it — the opposite of what a monitoring system is for (§4.4).

**A fact is never reported unobserved.** An unreachable poller yields no fact at all rather
than a stale or assumed one. Same discipline as Health's capability-drift check, and for the
same reason: a clean-looking answer from a check that did not run is worse than an obvious gap,
because it is indistinguishable from a real one.

The first observation of a fact is not a change (`FactChange.is_first_observation`). On a fresh
install every fact would otherwise look like news, burying the one thing that actually moved
under a full inventory dump on day one.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from common.frozen_dict import FrozenDict

from ..contracts import FactChange, PollResult, TrackedFact, TrackedFactKind, utcnow
from ..errors import TelemetreesError, UpstreamUnreachable, code_for
from ..metrics import TelemetreesMetricsCollector
from .errors import NoPollerForFactKind, PollerAlreadyRegistered
from .registry import TrackedDependencyRegistry

#: A probe answers one fact kind for one dependency, returning `(value, detail)` or `None` when
#: there is genuinely nothing to report. Deliberately narrow: this orchestrator compares strings
#: and knows nothing about what any particular fact means, which is what lets one loop serve six
#: fact kinds without a match statement over them.
FactProbe = Callable[[str], "tuple[str, str] | None"]


class PollerRegistry:
    """Which mechanism answers which fact kind (§3's "polling is not uniform").

    Genuinely mutable internal state populated at startup, so a plain `dict` behind a lock
    rather than a `FrozenDict` — §2.1.1 draws that line at intent, and this is not a constant.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._probes: dict[TrackedFactKind, FactProbe] = {}

    def register(self, kind: TrackedFactKind, probe: FactProbe) -> None:
        """Bind a probe to a fact kind.

        Raises on a duplicate rather than replacing: which poller answers a kind would otherwise
        depend on import order, and two probes for one kind would disagree exactly where it
        mattered.
        """
        with self._lock:
            if kind in self._probes:
                raise PollerAlreadyRegistered(kind.value)
            self._probes[kind] = probe

    def get(self, kind: TrackedFactKind) -> FactProbe | None:
        with self._lock:
            return self._probes.get(kind)

    def require(self, kind: TrackedFactKind) -> FactProbe:
        probe = self.get(kind)
        if probe is None:
            raise NoPollerForFactKind(kind.value)
        return probe

    def covered_kinds(self) -> frozenset[TrackedFactKind]:
        with self._lock:
            return frozenset(self._probes)

    def missing_for(self, registry: TrackedDependencyRegistry) -> frozenset[TrackedFactKind]:
        """Declared fact kinds nothing can answer — Warden §8's coverage question.

        A method rather than something the test derives for itself, so an operator-facing status
        view can answer "is anything registered that nobody is actually watching" without
        reimplementing the comparison.
        """
        return frozenset(registry.declared_fact_kinds() - self.covered_kinds())


class WardenPoller:
    """Runs one polling pass and reports what changed (§5)."""

    def __init__(
        self,
        registry: TrackedDependencyRegistry,
        pollers: PollerRegistry,
        *,
        metrics: TelemetreesMetricsCollector | None = None,
    ) -> None:
        self._registry = registry
        self._pollers = pollers
        self._metrics = metrics or TelemetreesMetricsCollector()
        self._lock = threading.Lock()
        self._last_seen: dict[tuple[str, str, str], str] = {}

    @property
    def metrics(self) -> TelemetreesMetricsCollector:
        return self._metrics

    def poll_once(self) -> PollResult:
        """One pass over every tracked dependency and every fact kind it declares."""
        changes: list[FactChange] = []
        unreachable: dict[str, str] = {}

        for dependency in self._registry.all_dependencies():
            for kind in dependency.fact_kinds:
                probe = self._pollers.get(kind)
                if probe is None:
                    unreachable[f"{dependency.name}:{kind.value}"] = "NO_POLLER_FOR_FACT_KIND"
                    continue
                self._metrics.increment("polls_attempted")
                try:
                    observed = probe(dependency.name)
                except (UpstreamUnreachable, TelemetreesError) as exc:
                    self._metrics.increment("polls_unreachable")
                    unreachable[f"{dependency.name}:{kind.value}"] = code_for(exc)
                    continue
                except Exception as exc:  # noqa: BLE001 - a pass never fails; see docstring
                    self._metrics.increment("polls_unreachable")
                    unreachable[f"{dependency.name}:{kind.value}"] = f"INTERNAL: {exc}"
                    continue

                if observed is None:
                    continue
                value, detail = observed
                fact = TrackedFact(
                    dependency=dependency.name,
                    kind=kind,
                    value=value,
                    observed_at=utcnow(),
                    detail=detail,
                )
                changes.append(self._fold(fact))

        return PollResult(
            changes=tuple(changes), unreachable=FrozenDict(unreachable), polled_at=utcnow()
        )

    def _fold(self, fact: TrackedFact) -> FactChange:
        """Compare an observation against what was last seen, and remember it."""
        self._metrics.increment("facts_observed")
        with self._lock:
            previous = self._last_seen.get(fact.key)
            self._last_seen[fact.key] = fact.value
        change = FactChange(fact=fact, previous=previous)
        if change.changed:
            self._metrics.increment("facts_changed")
            if fact.kind is TrackedFactKind.UPSTREAM_ISSUE_STATUS:
                self._metrics.increment("issue_state_changes_detected")
        return change

    def last_seen(self, fact_key: tuple[str, str, str]) -> str | None:
        with self._lock:
            return self._last_seen.get(fact_key)


__all__ = ["FactProbe", "PollerRegistry", "WardenPoller"]

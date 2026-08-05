"""The bench suite's classification technique, running continuously against real traffic (§3).

The payoff §3 names is **soft degradation**, not hard failure. An engine that is normally
CPU-bound suddenly behaving as if network-bound — a misconfigured execution provider falling
back to a slower path, a thermally throttling GPU — passes every up/down check there is and is
exactly what this exists to surface.

The classification itself is the bench suite's own empirical wall-time/CPU-time/RSS technique,
which `v3-plan-02-architecture.md`'s concurrency table classifies as negligible-cost. The
expensive part was always the workload being measured, and that belongs to whichever API is
doing the work, not to Health (§7).

Two properties this module holds itself to:

* **A clean finding is still a finding.** `degraded=False` is returned, not swallowed. An
  operator who only ever hears from a detector when it is unhappy has no way to distinguish
  "nothing is wrong" from "the detector stopped running" — the same reasoning §4.1 states for
  the drift check, applied here.
* **Too few samples is `INDETERMINATE`, never a guess.** §10's own framing: a check that cries
  wolf gets ignored exactly as fast as one that never fires.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable, Sequence

from .contracts import LiveDiagnosticFinding, LiveDiagnosticSample, WorkloadClass
from .metrics import HealthMetricsCollector

#: Below this many samples an operation is `INDETERMINATE` rather than classified.
MIN_SAMPLES_FOR_CLASSIFICATION: int = 5

#: How many recent samples per operation are kept. A bounded window is what makes this a
#: *live* diagnostic rather than a lifetime average — a lifetime average is precisely what
#: would hide a degradation that started an hour ago.
DEFAULT_WINDOW_SIZE: int = 64

#: CPU time at or above this fraction of wall time means the work was actually running, not
#: waiting. The complement is the wait fraction the two boundaries below are drawn against.
CPU_BOUND_RATIO: float = 0.75

#: Below this CPU/wall ratio the operation spent most of its time waiting on something. Which
#: *kind* of waiting is what `IO_BOUND` versus `NETWORK_BOUND` distinguishes, and wall time is
#: the only signal available here that separates them without instrumenting the callee.
WAITING_RATIO: float = 0.35

#: A waiting operation slower than this is network-shaped rather than local-IO-shaped. A local
#: disk read that takes a quarter second is unusual; a round trip that does is ordinary.
NETWORK_LATENCY_MS: float = 250.0

#: RSS growth above this dominates the classification: an operation ballooning memory is
#: memory-bound whatever its CPU ratio says, and that is the signal worth surfacing.
MEMORY_BOUND_RSS_MB: float = 256.0

#: Under this wall time there is nothing to classify — the measurement is noise.
NEGLIGIBLE_WALL_MS: float = 1.0


def classify(samples: Sequence[LiveDiagnosticSample]) -> WorkloadClass:
    """The empirical classification of one operation's recent samples (§3).

    Medians rather than means, deliberately: one pathological outlier — a cold start, a single
    page fault storm — must not be able to reclassify an operation on its own, and the whole
    value of this running continuously is that it reflects the steady state.
    """
    if len(samples) < MIN_SAMPLES_FOR_CLASSIFICATION:
        return WorkloadClass.INDETERMINATE

    wall = _median([s.wall_time_ms for s in samples])
    cpu = _median([s.cpu_time_ms for s in samples])
    rss = _median([s.rss_delta_mb for s in samples])

    if wall < NEGLIGIBLE_WALL_MS:
        return WorkloadClass.NEGLIGIBLE
    if rss >= MEMORY_BOUND_RSS_MB:
        return WorkloadClass.MEMORY_BOUND

    ratio = cpu / wall if wall > 0 else 0.0
    if ratio >= CPU_BOUND_RATIO:
        return WorkloadClass.CPU_BOUND
    if ratio <= WAITING_RATIO:
        return WorkloadClass.NETWORK_BOUND if wall >= NETWORK_LATENCY_MS else WorkloadClass.IO_BOUND
    return WorkloadClass.INDETERMINATE


class LiveDiagnostic:
    """Rolling per-operation sample windows and the degradation check over them.

    One instance per Health process. Baselines are registered rather than learned here: the
    bench suite already establishes what each operation's class is supposed to be, and having
    this module infer its own baseline from live traffic would mean a slow degradation quietly
    becomes the new normal — the exact failure it is meant to catch.
    """

    def __init__(
        self,
        *,
        window_size: int = DEFAULT_WINDOW_SIZE,
        metrics: HealthMetricsCollector | None = None,
    ) -> None:
        self._window_size = window_size
        self._metrics = metrics or HealthMetricsCollector()
        self._lock = threading.Lock()
        self._samples: dict[tuple[str, str], deque[LiveDiagnosticSample]] = {}
        self._baselines: dict[tuple[str, str], WorkloadClass] = {}

    def register_baseline(self, service: str, operation: str, expected: WorkloadClass) -> None:
        """Declare what the bench suite says this operation's class should be."""
        with self._lock:
            self._baselines[(service, operation)] = expected

    def record(self, sample: LiveDiagnosticSample) -> None:
        """Add one observation of real traffic.

        Never raises and never blocks on anything but its own lock: this is called from other
        services' hot paths, and a diagnostic that can fail the work it is measuring has cost
        more than it detects.
        """
        key = (sample.service, sample.operation)
        with self._lock:
            window = self._samples.get(key)
            if window is None:
                window = deque(maxlen=self._window_size)
                self._samples[key] = window
            window.append(sample)
        self._metrics.increment("diagnostic_samples_recorded")

    def finding(self, service: str, operation: str) -> LiveDiagnosticFinding:
        """Classify one operation and say whether it drifted from its baseline (§3)."""
        key = (service, operation)
        with self._lock:
            samples = tuple(self._samples.get(key, ()))
            baseline = self._baselines.get(key, WorkloadClass.INDETERMINATE)

        observed = classify(samples)
        degraded = _is_degradation(baseline, observed)
        if degraded:
            self._metrics.increment("soft_degradations_detected")
        return LiveDiagnosticFinding(
            service=service,
            operation=operation,
            baseline_class=baseline,
            observed_class=observed,
            sample_count=len(samples),
            degraded=degraded,
            detail=_detail(baseline, observed, len(samples)),
        )

    def findings(self) -> tuple[LiveDiagnosticFinding, ...]:
        """Every tracked operation's finding, degraded or not."""
        with self._lock:
            keys = sorted(set(self._samples) | set(self._baselines))
        return tuple(self.finding(service, operation) for service, operation in keys)


def _is_degradation(baseline: WorkloadClass, observed: WorkloadClass) -> bool:
    """Whether an observed class against a baseline is worth an operator's attention.

    `INDETERMINATE` on either side is never a degradation. Not knowing is not the same as
    knowing something is wrong, and reporting it as one is how a detector earns the reputation
    that gets it ignored (§10).
    """
    if WorkloadClass.INDETERMINATE in (baseline, observed):
        return False
    return baseline is not observed


def _detail(baseline: WorkloadClass, observed: WorkloadClass, count: int) -> str:
    if count < MIN_SAMPLES_FOR_CLASSIFICATION:
        return f"{count} samples, below the {MIN_SAMPLES_FOR_CLASSIFICATION} needed to classify"
    if _is_degradation(baseline, observed):
        return f"expected {baseline.value}, observing {observed.value} over {count} samples"
    return f"{observed.value} over {count} samples, matching baseline"


def _median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


__all__ = [
    "CPU_BOUND_RATIO",
    "DEFAULT_WINDOW_SIZE",
    "MEMORY_BOUND_RSS_MB",
    "MIN_SAMPLES_FOR_CLASSIFICATION",
    "NEGLIGIBLE_WALL_MS",
    "NETWORK_LATENCY_MS",
    "WAITING_RATIO",
    "LiveDiagnostic",
    "classify",
]

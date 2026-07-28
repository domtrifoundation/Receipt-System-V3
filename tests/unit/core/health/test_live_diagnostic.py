"""The live diagnostic (`v3-deepdive-20-health-api.md` §3).

§10's third named testing hook is the soft-degradation detection test: "a bench case where a
normally-CPU-bound engine is forced into an artificially slow/network-bound-looking pattern,
confirming the live diagnostic actually flags it rather than only catching hard failures."
That is `test_cpu_bound_engine_behaving_network_bound_is_flagged` below.

The other half matters just as much and is tested alongside it: an operation matching its
baseline reports `degraded=False` rather than nothing, and too few samples reports
`INDETERMINATE` rather than a guess. A detector that cries wolf gets ignored exactly as fast
as one that never fires.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.health.contracts import LiveDiagnosticSample, WorkloadClass
from core.health.live_diagnostic import (
    MIN_SAMPLES_FOR_CLASSIFICATION,
    LiveDiagnostic,
    classify,
)

BASE = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)


def samples(
    count: int,
    *,
    wall: float,
    cpu: float,
    rss: float = 0.0,
    service: str = "ocr",
    operation: str = "recognize",
) -> list[LiveDiagnosticSample]:
    return [
        LiveDiagnosticSample(
            service=service,
            operation=operation,
            wall_time_ms=wall,
            cpu_time_ms=cpu,
            rss_delta_mb=rss,
            observed_at=BASE + timedelta(seconds=i),
        )
        for i in range(count)
    ]


def test_cpu_dominant_work_is_cpu_bound():
    assert classify(samples(10, wall=100.0, cpu=95.0)) is WorkloadClass.CPU_BOUND


def test_slow_waiting_work_is_network_bound():
    assert classify(samples(10, wall=800.0, cpu=10.0)) is WorkloadClass.NETWORK_BOUND


def test_fast_waiting_work_is_io_bound():
    """Wall time is what separates local IO from a round trip.

    A local disk read taking a quarter second is unusual; a network round trip that does is
    ordinary. Without that split every waiting operation would look identical and the
    degradation this module exists to catch — CPU-bound work turning network-shaped — would
    be indistinguishable from ordinary disk access.
    """
    assert classify(samples(10, wall=20.0, cpu=2.0)) is WorkloadClass.IO_BOUND


def test_memory_growth_dominates_the_classification():
    assert classify(samples(10, wall=100.0, cpu=95.0, rss=512.0)) is WorkloadClass.MEMORY_BOUND


def test_trivial_work_is_negligible():
    assert classify(samples(10, wall=0.2, cpu=0.1)) is WorkloadClass.NEGLIGIBLE


def test_too_few_samples_is_indeterminate_not_a_guess():
    few = samples(MIN_SAMPLES_FOR_CLASSIFICATION - 1, wall=100.0, cpu=95.0)

    assert classify(few) is WorkloadClass.INDETERMINATE


def test_one_outlier_does_not_reclassify_an_operation():
    """Medians, not means — the whole value here is reflecting the steady state.

    A single cold start or page-fault storm reclassifying an engine would produce an alert
    every deploy, which is how a detector stops being read.
    """
    window = samples(9, wall=100.0, cpu=95.0)
    window.append(
        LiveDiagnosticSample(
            service="ocr",
            operation="recognize",
            wall_time_ms=9000.0,
            cpu_time_ms=5.0,
            rss_delta_mb=0.0,
            observed_at=BASE,
        )
    )

    assert classify(window) is WorkloadClass.CPU_BOUND


def test_cpu_bound_engine_behaving_network_bound_is_flagged():
    """§10's soft-degradation detection test.

    The scenario is a real one §3 names: a misconfigured execution provider falling back to a
    slower path, or a thermally throttling GPU. Nothing has crashed, every up/down check
    passes, and this is the only thing that notices.
    """
    diagnostic = LiveDiagnostic()
    diagnostic.register_baseline("ocr", "recognize", WorkloadClass.CPU_BOUND)
    for sample in samples(10, wall=900.0, cpu=12.0):
        diagnostic.record(sample)

    finding = diagnostic.finding("ocr", "recognize")

    assert finding.degraded
    assert finding.observed_class is WorkloadClass.NETWORK_BOUND
    assert finding.baseline_class is WorkloadClass.CPU_BOUND
    assert "expected CPU_BOUND, observing NETWORK_BOUND" in finding.detail


def test_healthy_operation_reports_a_clean_finding_rather_than_nothing():
    """§4.1's reasoning applied here: a clean bill of health is itself a useful fact.

    An operator who only ever hears from a detector when it is unhappy cannot tell "nothing is
    wrong" from "the detector stopped running".
    """
    diagnostic = LiveDiagnostic()
    diagnostic.register_baseline("ocr", "recognize", WorkloadClass.CPU_BOUND)
    for sample in samples(10, wall=100.0, cpu=95.0):
        diagnostic.record(sample)

    finding = diagnostic.finding("ocr", "recognize")

    assert not finding.degraded
    assert finding.sample_count == 10
    assert "matching baseline" in finding.detail


def test_indeterminate_is_never_reported_as_a_degradation():
    diagnostic = LiveDiagnostic()
    diagnostic.register_baseline("ocr", "recognize", WorkloadClass.CPU_BOUND)
    for sample in samples(2, wall=100.0, cpu=95.0):
        diagnostic.record(sample)

    finding = diagnostic.finding("ocr", "recognize")

    assert not finding.degraded
    assert finding.observed_class is WorkloadClass.INDETERMINATE


def test_window_is_bounded_so_old_behaviour_stops_counting():
    """A lifetime average would hide a degradation that started an hour ago."""
    diagnostic = LiveDiagnostic(window_size=10)
    diagnostic.register_baseline("ocr", "recognize", WorkloadClass.CPU_BOUND)
    for sample in samples(20, wall=100.0, cpu=95.0):
        diagnostic.record(sample)
    for sample in samples(10, wall=900.0, cpu=12.0):
        diagnostic.record(sample)

    finding = diagnostic.finding("ocr", "recognize")

    assert finding.sample_count == 10
    assert finding.degraded


def test_findings_covers_every_tracked_operation():
    diagnostic = LiveDiagnostic()
    diagnostic.register_baseline("ocr", "recognize", WorkloadClass.CPU_BOUND)
    diagnostic.register_baseline("inference", "infer", WorkloadClass.CPU_BOUND)
    for sample in samples(10, wall=100.0, cpu=95.0):
        diagnostic.record(sample)

    found = {(f.service, f.operation) for f in diagnostic.findings()}

    assert found == {("ocr", "recognize"), ("inference", "infer")}


def test_degradations_are_counted():
    from core.health.metrics import HealthMetricsCollector

    metrics = HealthMetricsCollector()
    diagnostic = LiveDiagnostic(metrics=metrics)
    diagnostic.register_baseline("ocr", "recognize", WorkloadClass.CPU_BOUND)
    for sample in samples(10, wall=900.0, cpu=12.0):
        diagnostic.record(sample)
    diagnostic.finding("ocr", "recognize")

    snapshot = metrics.snapshot()
    assert snapshot.diagnostic_samples_recorded == 10
    assert snapshot.soft_degradations_detected == 1

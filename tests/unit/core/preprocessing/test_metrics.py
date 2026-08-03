"""`PreprocessingMetricsCollector` — same thread-safety guarantee `core/health/metrics.py`
already established, applied here."""

from __future__ import annotations

import threading

from core.preprocessing.contracts import PreprocessingMetrics
from core.preprocessing.metrics import COUNTER_NAMES, PreprocessingMetricsCollector


def test_every_preprocessing_metrics_field_has_a_matching_counter_name():
    assert set(COUNTER_NAMES) == set(PreprocessingMetrics.__dataclass_fields__)


def test_an_unknown_counter_name_is_ignored_not_raised():
    collector = PreprocessingMetricsCollector()
    collector.increment("this_counter_does_not_exist")
    assert collector.snapshot() == PreprocessingMetrics()


def test_snapshot_reflects_real_increments():
    collector = PreprocessingMetricsCollector()
    collector.increment("rasters_succeeded")
    collector.increment("rasters_succeeded")
    collector.increment("variants_run_on_opencl", amount=3)

    snap = collector.snapshot()
    assert snap.rasters_succeeded == 2
    assert snap.variants_run_on_opencl == 3
    assert snap.rasters_failed == 0


def test_concurrent_increments_from_many_threads_lose_no_updates():
    collector = PreprocessingMetricsCollector()
    increments_per_thread = 500
    thread_count = 16

    def hammer() -> None:
        for _ in range(increments_per_thread):
            collector.increment("variants_succeeded")

    threads = [threading.Thread(target=hammer) for _ in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert collector.snapshot().variants_succeeded == increments_per_thread * thread_count

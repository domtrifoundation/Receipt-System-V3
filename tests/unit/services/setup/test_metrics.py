"""`SetupMetricsCollector` — the same thread-safety guarantee `core/health/metrics.py` already
established, applied here.

The one property worth a real test rather than a glance: concurrent increments from multiple
threads must not lose updates to the GIL's incidental atomicity not holding under free-threaded
3.14t (`docs/PRINCIPLES.md` §3.3.1) — this is exactly the scenario a plain unlocked `dict[k] +=
1` would silently corrupt under real contention, and exactly the scenario a single-threaded test
cannot catch by accident.
"""

from __future__ import annotations

import threading

from services.setup.contracts import SetupMetrics
from services.setup.metrics import COUNTER_NAMES, SetupMetricsCollector


def test_every_setup_metrics_field_has_a_matching_counter_name():
    assert set(COUNTER_NAMES) == {f for f in SetupMetrics.__dataclass_fields__}


def test_an_unknown_counter_name_is_ignored_not_raised():
    """Instrumentation is never allowed to crash the operation it observes."""
    collector = SetupMetricsCollector()
    collector.increment("this_counter_does_not_exist")
    assert collector.snapshot() == SetupMetrics()


def test_snapshot_reflects_real_increments():
    collector = SetupMetricsCollector()
    collector.increment("hardware_detections_run")
    collector.increment("hardware_detections_run")
    collector.increment("venvs_provisioned", amount=5)

    snap = collector.snapshot()
    assert snap.hardware_detections_run == 2
    assert snap.venvs_provisioned == 5
    assert snap.strip_errors == 0


def test_concurrent_increments_from_many_threads_lose_no_updates():
    collector = SetupMetricsCollector()
    increments_per_thread = 500
    thread_count = 16

    def hammer() -> None:
        for _ in range(increments_per_thread):
            collector.increment("wizard_steps_completed")

    threads = [threading.Thread(target=hammer) for _ in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert collector.snapshot().wizard_steps_completed == increments_per_thread * thread_count


def test_a_snapshot_is_immutable_and_independent_of_later_increments():
    collector = SetupMetricsCollector()
    collector.increment("strip_operations_run")
    first = collector.snapshot()

    collector.increment("strip_operations_run")
    second = collector.snapshot()

    assert first.strip_operations_run == 1
    assert second.strip_operations_run == 2

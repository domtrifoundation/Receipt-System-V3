"""`SleepStateStore` — live tracking of one Supervisor process's own service states."""

from __future__ import annotations

from supervisor.contracts import ServiceState
from supervisor.sleep_wake.state import SleepStateStore


def test_status_for_an_unknown_service_defaults_to_stopped():
    store = SleepStateStore()

    status = store.status_for("ocr")

    assert status.state is ServiceState.STOPPED
    assert status.last_activity_at is None


def test_mark_active_records_running_and_a_real_timestamp():
    store = SleepStateStore()

    store.mark_active("ocr")
    status = store.status_for("ocr")

    assert status.state is ServiceState.RUNNING
    assert status.last_activity_at is not None


def test_mark_sleeping_records_sleeping():
    store = SleepStateStore()
    store.mark_active("ocr")

    store.mark_sleeping("ocr")

    assert store.status_for("ocr").state is ServiceState.SLEEPING


def test_is_idle_expired_false_immediately_after_activity():
    store = SleepStateStore(idle_timeout_minutes=30)
    store.mark_active("ocr")

    assert store.is_idle_expired("ocr") is False


def test_is_idle_expired_false_for_a_never_class_service_regardless_of_activity():
    store = SleepStateStore(idle_timeout_minutes=0)
    store.mark_active("auth")

    assert store.is_idle_expired("auth") is False


def test_is_idle_expired_false_when_never_active():
    store = SleepStateStore()

    assert store.is_idle_expired("ocr") is False


def test_is_idle_expired_true_once_the_timeout_has_genuinely_elapsed():
    store = SleepStateStore(idle_timeout_minutes=0)
    store.mark_active("ocr")

    assert store.is_idle_expired("ocr") is True

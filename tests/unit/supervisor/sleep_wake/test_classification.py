"""§6.2's own sleep-policy classification table, verbatim."""

from __future__ import annotations

from supervisor.contracts import SleepPolicy
from supervisor.sleep_wake.classification import policy_for


def test_never_class_services():
    for name in ("auth", "gateway", "health", "persistence", "logs", "watchdog"):
        assert policy_for(name) is SleepPolicy.NEVER


def test_scheduled_only_class_services():
    assert policy_for("ingestion") is SleepPolicy.SCHEDULED_ONLY


def test_idle_timeout_class_services():
    for name in ("ocr", "preprocessing", "inference"):
        assert policy_for(name) is SleepPolicy.IDLE_TIMEOUT


def test_an_unclassified_service_defaults_to_never():
    """The fail-closed default (`docs/PRINCIPLES.md` §4.2) — an unclassified service is
    assumed to need to always be responsive, never guessed as safe to sleep."""
    assert policy_for("some_future_service_nobody_classified_yet") is SleepPolicy.NEVER

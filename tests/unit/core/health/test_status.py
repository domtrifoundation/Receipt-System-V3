"""The status layer (`v3-deepdive-20-health-api.md` §1).

The distinction these tests exist to protect is `UNKNOWN` versus `DOWN`, and `DEGRADED`
versus both. Health reports; it does not decide (§1) — and every one of those three states
means something different to Supervisor's rollout gate, so collapsing any pair would quietly
change a deployment decision.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from common.version import PROGRAM_VERSION
from core.health.contracts import DependencyReachability, ServiceState, ServiceStatus
from core.health.errors import UnknownService
from core.health.metrics import HealthMetricsCollector
from core.health.status import StatusRegistry, derive_state, self_report


def dep(name: str, reachable: bool) -> DependencyReachability:
    return DependencyReachability(
        name=name, reachable=reachable, checked_at=datetime(2026, 7, 28, tzinfo=timezone.utc)
    )


def test_all_dependencies_reachable_is_up():
    assert derive_state([dep("tesseract", True), dep("rapidocr", True)]) is ServiceState.UP


def test_missing_optional_dependency_is_degraded_not_down():
    """`docs/PRINCIPLES.md` §4.4: a missing OCR engine means that engine is unavailable.

    Reporting `DOWN` here would make Supervisor refuse a release that is serving perfectly
    well on its remaining engines — the concrete cost of not having a `DEGRADED` state.
    """
    state = derive_state([dep("tesseract", True), dep("google_vision", False)])

    assert state is ServiceState.DEGRADED


def test_missing_required_dependency_is_down():
    state = derive_state([dep("persistence", False)], required=["persistence"])

    assert state is ServiceState.DOWN


def test_not_running_is_down_regardless_of_dependencies():
    assert derive_state([dep("tesseract", True)], running=False) is ServiceState.DOWN


def test_self_report_carries_the_program_version_from_the_one_constant():
    """`docs/PROCESS_TOPOLOGY.md` §7 needs the running version on this record.

    Asserting it equals `common.version.PROGRAM_VERSION` rather than a literal is the point:
    a per-service copy of that string is exactly the drift the constant exists to prevent.
    """
    status = self_report("ocr", "ocr-1", version_commit="abc1234")

    assert status.version == PROGRAM_VERSION
    assert status.version_commit == "abc1234"


def test_registry_returns_a_fresh_report_unchanged(clock):
    registry = StatusRegistry(now=clock)
    registry.report(self_report("ocr", "ocr-1", now=clock))

    clock.advance(30)

    assert registry.get("ocr", "ocr-1").state is ServiceState.UP


def test_stale_report_ages_to_unknown_not_down(clock):
    """A service that stopped reporting is "I could not tell", never "I checked and it is dead".

    `UNKNOWN` is what lets Supervisor apply its own policy. Aging to `DOWN` here would hand
    Health the rollout decision its own boundary section refuses to take (§1).
    """
    registry = StatusRegistry(staleness_seconds=90, now=clock)
    registry.report(self_report("ocr", "ocr-1", now=clock))

    clock.advance(91)
    aged = registry.get("ocr", "ocr-1")

    assert aged.state is ServiceState.UNKNOWN
    assert "past the 90s window" in aged.detail


def test_never_reported_service_raises_rather_than_reporting_unknown(clock):
    """A typo'd service name and a dead service are different operator problems."""
    registry = StatusRegistry(now=clock)

    with pytest.raises(UnknownService):
        registry.get("ocr", "never-existed")


def test_instances_of_one_service_are_tracked_separately(clock):
    registry = StatusRegistry(now=clock)
    registry.report(self_report("ocr", "ocr-1", now=clock))
    registry.report(self_report("ocr", "ocr-2", now=clock))
    registry.report(self_report("auth", "auth-1", now=clock))

    assert {s.instance_id for s in registry.instances("ocr")} == {"ocr-1", "ocr-2"}
    assert len(registry.all_statuses()) == 3


def test_one_instance_going_stale_does_not_age_its_sibling(clock):
    """Per-instance staleness, not per-service.

    Under A/B hot-swap two instances of one service genuinely run at once; letting a healthy
    one's report cover for a stale one would hide exactly the case the fleet screen exists for.
    """
    registry = StatusRegistry(staleness_seconds=90, now=clock)
    registry.report(self_report("ocr", "ocr-old", now=clock))
    clock.advance(91)
    registry.report(self_report("ocr", "ocr-new", now=clock))

    states = {s.instance_id: s.state for s in registry.instances("ocr")}

    assert states["ocr-old"] is ServiceState.UNKNOWN
    assert states["ocr-new"] is ServiceState.UP


def test_unreachable_dependencies_are_counted(clock):
    metrics = HealthMetricsCollector()
    registry = StatusRegistry(metrics=metrics, now=clock)

    registry.report(
        self_report(
            "ocr",
            "ocr-1",
            dependencies=[dep("google_vision", False), dep("azure_ocr", False)],
            now=clock,
        )
    )

    snapshot = metrics.snapshot()
    assert snapshot.status_reports_received == 1
    assert snapshot.status_probes_unreachable == 2


def test_status_is_frozen():
    status = self_report("ocr", "ocr-1")

    with pytest.raises(Exception):
        status.state = ServiceState.DOWN  # type: ignore[misc]


def test_dependency_detail_survives_the_registry(clock):
    registry = StatusRegistry(now=clock)
    reported = ServiceStatus(
        service="ocr",
        instance_id="ocr-1",
        state=ServiceState.DEGRADED,
        version=PROGRAM_VERSION,
        version_commit="deadbee",
        reported_at=clock(),
        dependencies=(dep("google_vision", False),),
        detail="cloud tier unreachable",
    )
    registry.report(reported)

    assert registry.get("ocr", "ocr-1").detail == "cloud tier unreachable"

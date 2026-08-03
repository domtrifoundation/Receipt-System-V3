"""`boot_sequence.py` — real dependency-ordered subprocess launch, health-gated by a real
gRPC-reachability probe. Every test here launches a genuine `core/geo_address/service.py`
subprocess, never a mock."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor.boot_sequence import boot_many, launch_one, topological_order
from supervisor.contracts import ServiceSpec

from .conftest import free_port, run

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_topological_order_respects_dependencies():
    a = ServiceSpec(name="a", import_path="x", serve_module="x", address="x")
    b = ServiceSpec(name="b", import_path="x", serve_module="x", address="x", depends_on=("a",))
    c = ServiceSpec(name="c", import_path="x", serve_module="x", address="x", depends_on=("b",))

    ordered = topological_order((c, a, b))

    assert [s.name for s in ordered] == ["a", "b", "c"]


def test_topological_order_raises_on_a_cycle():
    a = ServiceSpec(name="a", import_path="x", serve_module="x", address="x", depends_on=("b",))
    b = ServiceSpec(name="b", import_path="x", serve_module="x", address="x", depends_on=("a",))

    with pytest.raises(ValueError, match="cycle"):
        topological_order((a, b))


def test_topological_order_raises_on_an_unknown_dependency():
    a = ServiceSpec(name="a", import_path="x", serve_module="x", address="x", depends_on=("nope",))

    with pytest.raises(ValueError, match="unknown service"):
        topological_order((a,))


def test_launch_one_boots_a_real_service_and_confirms_reachability(geo_address_spec, killer):
    result = run(launch_one(geo_address_spec, REPO_ROOT, timeout_seconds=15.0))
    if result.pid:
        killer.append(result.pid)

    assert result.ok is True
    assert result.pid is not None
    assert result.became_healthy_at is not None


def test_launch_one_reports_failure_for_a_nonexistent_module():
    spec = ServiceSpec(
        name="broken", import_path="core.geo_address", serve_module="core.does_not_exist.service",
        address=f"127.0.0.1:{free_port()}",
    )

    result = run(launch_one(spec, REPO_ROOT, timeout_seconds=5.0))

    assert result.ok is False
    assert "never became reachable" in result.error_detail


def test_boot_many_stops_at_the_first_failure(geo_address_spec, killer):
    broken = ServiceSpec(
        name="broken", import_path="core.geo_address", serve_module="core.does_not_exist.service",
        address=f"127.0.0.1:{free_port()}", depends_on=(geo_address_spec.name,),
    )
    never_launched = ServiceSpec(
        name="never_launched", import_path="core.geo_address", serve_module="core.geo_address.service",
        address=f"127.0.0.1:{free_port()}", depends_on=("broken",),
    )

    report = run(boot_many((never_launched, broken, geo_address_spec), REPO_ROOT, channel="dev", timeout_seconds=5.0))
    for s in report.services:
        if s.pid:
            killer.append(s.pid)

    assert report.ok is False
    assert [s.name for s in report.services] == [geo_address_spec.name, "broken"]
    assert report.failed_services == ("broken",)


def test_boot_many_reports_ok_when_every_service_becomes_healthy(geo_address_spec, killer):
    report = run(boot_many((geo_address_spec,), REPO_ROOT, channel="dev", timeout_seconds=15.0))
    for s in report.services:
        if s.pid:
            killer.append(s.pid)

    assert report.ok is True


def test_boot_many_calls_on_result_once_per_service_as_it_completes(geo_address_spec, killer):
    """The TUI's Boot Sequence screen's own live-progress seam."""
    seen = []

    report = run(boot_many((geo_address_spec,), REPO_ROOT, channel="dev", timeout_seconds=15.0, on_result=seen.append))
    for s in report.services:
        if s.pid:
            killer.append(s.pid)

    assert [r.name for r in seen] == [geo_address_spec.name]
    assert seen[0].ok is True

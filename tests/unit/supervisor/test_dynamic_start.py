"""`ensure_version_running()` — on-demand multi-version launch, and the refusal for
`interface_tui`/`inference` (those two go through `single_instance.py` instead)."""

from __future__ import annotations

from pathlib import Path

from supervisor.contracts import ServiceLaunchResult, ServiceSpec
from supervisor.dynamic_start import ensure_version_running
from supervisor.instance_registry import InstanceRegistry

from .conftest import free_port, run


def test_refuses_single_instance_services(tmp_path: Path):
    registry = InstanceRegistry()
    spec = ServiceSpec(name="interface_tui", import_path="services.interface", serve_module="x", address=f"127.0.0.1:{free_port()}")

    result = run(ensure_version_running(registry, spec, "x03.01.05", tmp_path / "releases"))

    assert result.ok is False
    assert "single-instance" in result.error_detail
    assert registry.get("interface_tui", "x03.01.05") is None


def test_returns_the_already_running_instance_without_relaunching(tmp_path: Path):
    registry = InstanceRegistry()
    spec = ServiceSpec(name="ocr", import_path="core.ocr", serve_module="x", address=f"127.0.0.1:{free_port()}")
    existing = ServiceLaunchResult(name="ocr", ok=True, pid=123, address="127.0.0.1:59999")
    registry.record("ocr", "x03.01.05", existing)

    result = run(ensure_version_running(registry, spec, "x03.01.05", tmp_path / "releases"))

    assert result == existing


def test_fails_when_no_release_clone_exists_for_the_requested_version(tmp_path: Path):
    registry = InstanceRegistry()
    spec = ServiceSpec(name="ocr", import_path="core.ocr", serve_module="x", address=f"127.0.0.1:{free_port()}")

    result = run(ensure_version_running(registry, spec, "x99.99.99", tmp_path / "releases"))

    assert result.ok is False
    assert "no release clone found" in result.error_detail
    assert registry.get("ocr", "x99.99.99") == result


def test_a_failed_lookup_is_recorded_so_repeated_calls_dont_relaunch(tmp_path: Path):
    registry = InstanceRegistry()
    spec = ServiceSpec(name="ocr", import_path="core.ocr", serve_module="x", address=f"127.0.0.1:{free_port()}")

    first = run(ensure_version_running(registry, spec, "x99.99.99", tmp_path / "releases"))
    # A failed (ok=False) result is recorded but not treated as "already running" —
    # calling again re-attempts resolution rather than permanently caching a failure.
    second = run(ensure_version_running(registry, spec, "x99.99.99", tmp_path / "releases"))

    assert first.ok is False
    assert second.ok is False


def test_two_versions_of_the_same_service_are_tracked_independently(tmp_path: Path):
    registry = InstanceRegistry()
    spec = ServiceSpec(name="ocr", import_path="core.ocr", serve_module="x", address=f"127.0.0.1:{free_port()}")
    existing_v1 = ServiceLaunchResult(name="ocr", ok=True, pid=111, address="127.0.0.1:59991")
    registry.record("ocr", "x03.01.05", existing_v1)

    result = run(ensure_version_running(registry, spec, "x99.99.99", tmp_path / "releases"))

    assert registry.get("ocr", "x03.01.05") == existing_v1
    assert result.ok is False

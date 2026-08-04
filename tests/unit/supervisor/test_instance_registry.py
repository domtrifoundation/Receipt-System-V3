"""`InstanceRegistry` — real per-`(service_name, version)` running-instance tracking, the
in-memory state multi-version-concurrent serving needs and single-instance boot never had."""

from __future__ import annotations

from supervisor.contracts import ServiceLaunchResult
from supervisor.instance_registry import InstanceRegistry


def _result(name: str, *, ok: bool = True, pid: int | None = 111) -> ServiceLaunchResult:
    return ServiceLaunchResult(name=name, ok=ok, pid=pid, address="127.0.0.1:50999")


def test_get_on_an_empty_registry_returns_none():
    registry = InstanceRegistry()

    assert registry.get("ocr", "x03.01.05") is None


def test_record_and_get_round_trip():
    registry = InstanceRegistry()
    result = _result("ocr")

    registry.record("ocr", "x03.01.05", result)

    assert registry.get("ocr", "x03.01.05") == result


def test_two_versions_of_the_same_service_coexist_independently():
    registry = InstanceRegistry()
    v1 = _result("ocr", pid=111)
    v2 = _result("ocr", pid=222)

    registry.record("ocr", "x03.01.05", v1)
    registry.record("ocr", "x03.01.06", v2)

    assert registry.get("ocr", "x03.01.05") == v1
    assert registry.get("ocr", "x03.01.06") == v2


def test_forget_removes_only_the_targeted_entry():
    registry = InstanceRegistry()
    registry.record("ocr", "x03.01.05", _result("ocr"))
    registry.record("ocr", "x03.01.06", _result("ocr"))

    registry.forget("ocr", "x03.01.05")

    assert registry.get("ocr", "x03.01.05") is None
    assert registry.get("ocr", "x03.01.06") is not None


def test_all_for_service_only_returns_that_services_own_versions():
    registry = InstanceRegistry()
    registry.record("ocr", "x03.01.05", _result("ocr"))
    registry.record("preprocessing", "x03.01.05", _result("preprocessing"))

    versions = registry.all_for_service("ocr")

    assert [v for v, _ in versions] == ["x03.01.05"]


def test_all_pids_collects_across_every_tracked_instance():
    registry = InstanceRegistry()
    registry.record("ocr", "x03.01.05", _result("ocr", pid=111))
    registry.record("ocr", "x03.01.06", _result("ocr", pid=222))

    assert set(registry.all_pids()) == {111, 222}

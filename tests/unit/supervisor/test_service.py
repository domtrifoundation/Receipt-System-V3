"""`SupervisorServicer` — wires arbitration, rollback, sleep_wake, version pins, and
single-instance restart to `supervisor.proto`'s wire surface."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from supervisor.generated import supervisor_pb2 as pb  # noqa: E402
from supervisor.service import SupervisorServicer  # noqa: E402

from .conftest import pid_listening_on, run  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def _servicer(tmp_path, geo_address_spec):
    return SupervisorServicer(tmp_path, {"geo_address": geo_address_spec})


def test_get_active_release_rpc_reports_unknown_channel(tmp_path, geo_address_spec):
    servicer = _servicer(tmp_path, geo_address_spec)

    response = run(servicer.GetActiveRelease(pb.ChannelRequest(channel="stable")))

    assert response.error_code == "UNKNOWN_CHANNEL"


def test_get_active_release_rpc_returns_a_real_active_release(tmp_path, geo_address_spec):
    servicer = _servicer(tmp_path, geo_address_spec)
    servicer._arbitrator.set_active("stable", REPO_ROOT)

    response = run(servicer.GetActiveRelease(pb.ChannelRequest(channel="stable")))

    assert response.error_code == ""
    assert response.release_dir == str(REPO_ROOT)


def test_force_wake_rpc_launches_a_real_service(tmp_path, geo_address_spec, killer):
    """`ForceWake`'s own RPC response carries no `pid` (matching `supervisor.proto`'s own
    §8 sketch), so teardown finds the real launched process the honest way — asking the
    OS who is actually listening on the address `ForceWake` just made reachable."""
    servicer = _servicer(tmp_path, geo_address_spec)
    servicer._arbitrator.set_active("stable", REPO_ROOT)

    response = run(servicer.ForceWake(pb.ForceWakeRequest(service_name="geo_address", requested_by="owner-1")))

    assert response.woke is True
    status = run(servicer.GetSleepStatus(pb.ServiceStatusRequest(service_name="geo_address")))
    assert status.state == "running"

    port = int(geo_address_spec.address.rsplit(":", 1)[1])
    pid = pid_listening_on(port)
    if pid:
        killer.append(pid)


def test_force_wake_rpc_reports_unknown_service(tmp_path, geo_address_spec):
    servicer = _servicer(tmp_path, geo_address_spec)
    servicer._arbitrator.set_active("stable", REPO_ROOT)

    response = run(servicer.ForceWake(pb.ForceWakeRequest(service_name="not_registered", requested_by="owner-1")))

    assert response.woke is False
    assert response.error_code == "UNKNOWN_SERVICE"


def test_force_wake_rpc_reports_no_active_release(tmp_path, geo_address_spec):
    servicer = _servicer(tmp_path, geo_address_spec)

    response = run(servicer.ForceWake(pb.ForceWakeRequest(service_name="geo_address", requested_by="owner-1")))

    assert response.woke is False
    assert response.error_code == "NO_ACTIVE_RELEASE"


def test_get_sleep_status_rpc_reports_the_real_classification(tmp_path, geo_address_spec):
    servicer = _servicer(tmp_path, geo_address_spec)

    response = run(servicer.GetSleepStatus(pb.ServiceStatusRequest(service_name="ocr")))

    assert response.policy == "idle_timeout"
    assert response.state == "stopped"


def test_pin_service_version_rpc_round_trips(tmp_path, geo_address_spec):
    servicer = _servicer(tmp_path, geo_address_spec)

    response = run(servicer.PinServiceVersion(pb.PinRequest(
        channel="beta", service_name="ocr", pinned_version="x03.01.05", pinned_by="owner-1",
    )))

    assert response.pinned_version == "x03.01.05"

    listed = run(servicer.ListServiceVersionPins(pb.ChannelRequest(channel="beta")))
    assert [p.service_name for p in listed.pins] == ["ocr"]


def test_pin_service_version_rpc_scoped_to_one_service_one_channel(tmp_path, geo_address_spec):
    """§7's own named testing hook, at the RPC layer."""
    servicer = _servicer(tmp_path, geo_address_spec)
    run(servicer.PinServiceVersion(pb.PinRequest(channel="beta", service_name="ocr", pinned_version="x03.01.05", pinned_by="owner-1")))

    listed = run(servicer.ListServiceVersionPins(pb.ChannelRequest(channel="beta")))

    assert all(p.service_name == "ocr" for p in listed.pins)


def test_trigger_rollback_rpc_reports_no_prior_release(tmp_path, geo_address_spec):
    servicer = _servicer(tmp_path, geo_address_spec)
    servicer._arbitrator.set_active("stable", REPO_ROOT)

    response = run(servicer.TriggerRollback(pb.RollbackRequest(channel="stable")))

    assert response.ok is False
    assert response.error_code == "NO_PRIOR_RELEASE"


def test_restart_service_on_version_rpc_rejects_a_non_single_instance_service(tmp_path, geo_address_spec):
    servicer = _servicer(tmp_path, geo_address_spec)

    async def collect():
        return [p async for p in servicer.RestartServiceOnVersion(pb.RestartRequest(service_name="ocr", target_version="1.0"), None)]

    results = run(collect())

    assert results[-1].stage == "failed"
    assert "not a single-instance service" in results[-1].error_detail


def test_restart_service_on_version_rpc_reports_unregistered_service(tmp_path, geo_address_spec):
    servicer = _servicer(tmp_path, geo_address_spec)

    async def collect():
        return [p async for p in servicer.RestartServiceOnVersion(pb.RestartRequest(service_name="inference", target_version="1.0"), None)]

    results = run(collect())

    assert results[-1].stage == "failed"
    assert "no spec registered" in results[-1].error_detail

"""The gRPC servicers (`v3-deepdive-20-health-api.md` §8, watchdog §7).

Two things are being protected here.

**Errors are data, never a raised gRPC status** (`docs/PRINCIPLES.md` §4.1) — and the sharper
case, that a *rejected* reservation is not an error at all. A client that read a capacity
rejection as a failure would surface an error dialog for what §5.1 describes as a routine
"fall back to CPU or queue" decision.

**The translation layer is thin.** Every real decision lives underneath, so these tests assert
the servicer faithfully passes things through rather than re-deciding anything — including the
one place it does exercise judgement, `status_from_wire`, where an unreadable timestamp must
not be silently re-stamped with the server's clock.
"""

from __future__ import annotations

import pytest

from core.health.resource_ledger import ResourceLedger, StaticHardwareProfile
from core.health.service import HealthServicer, WatchdogServicer, status_from_wire
from core.health.status import StatusRegistry, self_report
from core.health.watchdog.kicks import KickRegistry
from core.health.watchdog.timeout_detector import TimeoutDetector

pb = pytest.importorskip(
    "core.health.generated.health_pb2",
    reason="grpcio/protobuf has no wheel on this interpreter yet (docs/MAINTENANCE.md §3)",
)


@pytest.fixture
def servicer(clock, profile):
    return HealthServicer(
        registry=StatusRegistry(now=clock),
        ledger=ResourceLedger(profile=profile, ttl_seconds=120, now=clock),
    )


def test_reserve_grant_round_trips(servicer):
    response = servicer.ReserveResource(
        pb.ReserveRequest(owning_api="inference", device_id="gpu:0", requested_mb=2048), None
    )

    assert response.granted
    assert response.reservation.owning_api == "inference"
    assert response.reservation.expires_at != ""
    assert response.rejection_reason == ""
    assert response.error_code == ""


def test_capacity_rejection_is_not_an_error_on_the_wire(servicer):
    """§5.1 across the boundary: `rejection_reason` set, `error_code` empty."""
    servicer.ReserveResource(
        pb.ReserveRequest(owning_api="inference", device_id="gpu:1", requested_mb=4000), None
    )

    response = servicer.ReserveResource(
        pb.ReserveRequest(owning_api="ocr", device_id="gpu:1", requested_mb=512), None
    )

    assert not response.granted
    assert response.rejection_reason == "INSUFFICIENT_CAPACITY"
    assert response.error_code == ""


def test_unknown_reservation_release_returns_an_error_code_not_a_raise(servicer):
    response = servicer.ReleaseResource(pb.ReleaseRequest(reservation_id="nope"), None)

    assert not response.released
    assert response.error_code == "RESERVATION_NOT_FOUND"
    assert response.error_detail


def test_refresh_after_expiry_returns_the_expired_code(servicer, clock):
    granted = servicer.ReserveResource(
        pb.ReserveRequest(owning_api="ocr", device_id="gpu:0", requested_mb=128), None
    )
    clock.advance(121)

    response = servicer.RefreshReservation(
        pb.RefreshRequest(reservation_id=granted.reservation.reservation_id), None
    )

    assert not response.granted
    assert response.error_code == "RESERVATION_EXPIRED"


def test_report_then_get_status_round_trips(servicer, clock):
    reported = self_report("ocr", "ocr-1", version_commit="abc1234", now=clock)
    servicer.ReportStatus(
        pb.ReportStatusRequest(
            status=pb.ServiceStatus(
                service=reported.service,
                instance_id=reported.instance_id,
                state=reported.state.value,
                version=reported.version,
                version_commit=reported.version_commit,
                reported_at=reported.reported_at.isoformat(),
            )
        ),
        None,
    )

    response = servicer.GetStatus(pb.StatusRequest(service="ocr", instance_id="ocr-1"), None)

    assert response.statuses[0].version_commit == "abc1234"
    assert response.statuses[0].state == "UP"


def test_status_with_unreadable_timestamp_is_refused_not_restamped():
    """Re-stamping would defeat the staleness window entirely.

    A dead service whose reports were silently given the server's clock would read `UP`
    forever, which is precisely what `status.py`'s aging exists to prevent.
    """
    message = pb.ServiceStatus(
        service="ocr", instance_id="ocr-1", state="UP", reported_at="not-a-time"
    )

    assert status_from_wire(message) is None


def test_unknown_service_query_returns_an_error_code(servicer):
    response = servicer.GetStatus(
        pb.StatusRequest(service="ocr", instance_id="never-existed"), None
    )

    assert response.error_code == "UNKNOWN_SERVICE"
    assert list(response.statuses) == []


def test_drift_response_reports_clean_findings_too(servicer):
    response = servicer.GetCapabilityDrift(pb.DriftRequest(), None)

    assert response.any_drifted == any(f.drifted for f in response.findings)


def test_watchdog_kick_and_silence_round_trip(clock):
    kicks = KickRegistry(now=clock)
    watchdog = WatchdogServicer(kicks=kicks, detector=TimeoutDetector(kicks, now=clock))

    ack = watchdog.Kick(
        pb.HeartbeatRequest(service="ocr", instance_id="ocr-1", version_commit="abc1234"), None
    )
    clock.advance(61)
    silence = watchdog.GetSilentServices(pb.SilenceCheckRequest(), None)

    assert ack.accepted
    assert list(silence.silent_services) == ["ocr"]
    assert silence.states[0].liveness == "SILENT"
    assert silence.states[0].version_commit == "abc1234"


def test_malformed_kick_is_refused_as_data(clock):
    watchdog = WatchdogServicer(kicks=KickRegistry(now=clock))

    ack = watchdog.Kick(pb.HeartbeatRequest(service="", instance_id="ocr-1"), None)

    assert not ack.accepted
    assert ack.error_code == "INVALID_HEARTBEAT"


def test_watchdog_surface_has_no_restart_rpc():
    """watchdog §1: Watchdog detects and reports; Supervisor acts.

    Asserted against the generated descriptor rather than the Python class, so adding a
    restart RPC to the `.proto` fails here even before anyone implements it.
    """
    from core.health.generated import health_pb2_grpc as pb_grpc

    methods = [m for m in dir(pb_grpc.WatchdogServiceServicer) if not m.startswith("_")]

    assert sorted(methods) == ["GetSilentServices", "Kick"]

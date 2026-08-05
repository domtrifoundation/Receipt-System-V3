"""The `HealthService` and `WatchdogService` gRPC servicers — thin by design (§8, watchdog §7).

Every real decision lives in `status.py`, `resource_ledger.py`, `live_diagnostic.py`,
`capability_drift.py` and `watchdog/`. This file translates protobuf messages to and from the
contract types and nothing else, which is what keeps the guarantees properties of the package
rather than of this one file: there is no RPC here that could restart a process or gate a
rollout even if this file were written carelessly, because no module underneath it exposes a
way to (§1 — Health reports, it does not decide).

**Errors are data** (`docs/PRINCIPLES.md` §4.1): every response carries `error_code` and
`error_detail`; nothing raises across the boundary. The one thing to keep straight is that a
*rejected* reservation is not an error — §5.1 says a rejection means the caller falls back to
CPU or queues — so `rejection_reason` is populated and `error_code` stays empty.

**Concurrency**: `grpc.server` with a thread pool, matching §7's classification of status
checks and reservation calls as the highest-frequency operations in this API. The state they
touch is lock-guarded rather than GIL-dependent, since this project targets free-threaded
3.14t (`docs/PRINCIPLES.md` §3.3.1).

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly as
`core/logs/service.py` does, so this package stays importable — and its tests meaningful — on
an interpreter with no `grpcio` wheel yet (3.15 today, per `docs/MAINTENANCE.md` §3).
"""

from __future__ import annotations

from concurrent import futures
from datetime import datetime

from .capability_drift import ConfigReader, any_drifted, check_capability_drift
from .contracts import (
    DependencyReachability,
    ServiceState,
    ServiceStatus,
)
from .errors import HealthError, code_for, summary_for
from .live_diagnostic import LiveDiagnostic
from .metrics import HealthMetricsCollector
from .resource_ledger import HardwareProfileReader, ResourceLedger
from .status import StatusRegistry
from .watchdog.errors import WatchdogError
from .watchdog.errors import code_for as watchdog_code_for
from .watchdog.kicks import KickRegistry
from .watchdog.timeout_detector import TimeoutDetector

DEFAULT_ADDRESS = "127.0.0.1:50061"


def _iso(value: datetime | None) -> str:
    """RFC 3339 out, empty string for absent.

    Empty rather than a sentinel date: a client rendering "never released" needs to tell that
    apart from a real timestamp, and no real timestamp is the empty string.
    """
    return value.isoformat() if value is not None else ""


def _parse_time(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def status_from_wire(message) -> ServiceStatus | None:
    """Wire `ServiceStatus` -> contract, or `None` if it cannot be read.

    An unparseable `reported_at` yields `None` rather than a status timestamped "now": a
    report whose own clock reading is unusable must not be silently re-stamped with the
    server's, because the staleness window in `status.py` is the only thing standing between
    a dead service and a permanent `UP`.
    """
    reported_at = _parse_time(message.reported_at)
    if reported_at is None or not message.service or not message.instance_id:
        return None
    try:
        state = ServiceState(message.state) if message.state else ServiceState.UNKNOWN
    except ValueError:
        state = ServiceState.UNKNOWN
    dependencies = tuple(
        DependencyReachability(
            name=d.name,
            reachable=d.reachable,
            checked_at=_parse_time(d.checked_at) or reported_at,
            latency_ms=d.latency_ms or None,
            detail=d.detail,
        )
        for d in message.dependencies
    )
    return ServiceStatus(
        service=message.service,
        instance_id=message.instance_id,
        state=state,
        version=message.version,
        version_commit=message.version_commit,
        reported_at=reported_at,
        queue_depth=message.queue_depth,
        dependencies=dependencies,
        detail=message.detail,
    )


def status_to_wire(status: ServiceStatus, pb):
    return pb.ServiceStatus(
        service=status.service,
        instance_id=status.instance_id,
        state=status.state.value,
        version=status.version,
        version_commit=status.version_commit,
        reported_at=_iso(status.reported_at),
        queue_depth=status.queue_depth,
        dependencies=[
            pb.DependencyReachability(
                name=d.name,
                reachable=d.reachable,
                checked_at=_iso(d.checked_at),
                latency_ms=d.latency_ms or 0.0,
                detail=d.detail,
            )
            for d in status.dependencies
        ],
        resource_utilization={k: str(v) for k, v in status.resource_utilization.items()},
        detail=status.detail,
    )


def reservation_to_wire(reservation, pb):
    return pb.ResourceReservation(
        reservation_id=reservation.reservation_id,
        owning_api=reservation.owning_api,
        device_id=reservation.device_id,
        reserved_mb=reservation.reserved_mb,
        reserved_at=_iso(reservation.reserved_at),
        expires_at=_iso(reservation.expires_at),
        released_at=_iso(reservation.released_at),
        release_reason=reservation.release_reason,
    )


class HealthServicer:
    """Implements `HealthService`. Registered by name, so importing the generated stubs is
    `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        *,
        registry: StatusRegistry | None = None,
        ledger: ResourceLedger | None = None,
        diagnostic: LiveDiagnostic | None = None,
        config: ConfigReader | None = None,
        metrics: HealthMetricsCollector | None = None,
    ) -> None:
        self._metrics = metrics or HealthMetricsCollector()
        self._registry = registry or StatusRegistry(metrics=self._metrics)
        self._ledger = ledger or ResourceLedger(metrics=self._metrics)
        self._diagnostic = diagnostic or LiveDiagnostic(metrics=self._metrics)
        self._config = config

    def GetStatus(self, request, context):  # noqa: N802 - gRPC method naming
        from .generated import health_pb2 as pb

        try:
            if request.service and request.instance_id:
                statuses = (self._registry.get(request.service, request.instance_id),)
            elif request.service:
                statuses = self._registry.instances(request.service)
            else:
                statuses = self._registry.all_statuses()
        except HealthError as exc:
            code = code_for(exc)
            return pb.StatusResponse(error_code=code, error_detail=summary_for(code))
        return pb.StatusResponse(statuses=[status_to_wire(s, pb) for s in statuses])

    def ReportStatus(self, request, context):  # noqa: N802
        from .generated import health_pb2 as pb

        status = status_from_wire(request.status)
        if status is None:
            return pb.ReportStatusAck(
                accepted=False,
                error_code="INVALID_STATUS_REPORT",
                error_detail="the report named no service/instance or carried an unreadable timestamp",
            )
        self._registry.report(status)
        return pb.ReportStatusAck(accepted=True)

    def ReserveResource(self, request, context):  # noqa: N802
        from .generated import health_pb2 as pb

        outcome = self._ledger.reserve(
            request.owning_api, request.device_id, request.requested_mb
        )
        return pb.ReservationResponse(
            granted=outcome.granted,
            reservation=(
                reservation_to_wire(outcome.reservation, pb) if outcome.reservation else None
            ),
            rejection_reason=(
                outcome.rejection_reason.value if outcome.rejection_reason else ""
            ),
            device_total_mb=outcome.device_total_mb,
            device_committed_mb=outcome.device_committed_mb,
            error_code=outcome.error_code,
            error_detail=outcome.error_detail,
        )

    def ReleaseResource(self, request, context):  # noqa: N802
        from .generated import health_pb2 as pb

        try:
            self._ledger.release(request.reservation_id, request.reason or "released")
        except HealthError as exc:
            code = code_for(exc)
            return pb.ReleaseAck(released=False, error_code=code, error_detail=summary_for(code))
        return pb.ReleaseAck(released=True)

    def RefreshReservation(self, request, context):  # noqa: N802
        from .generated import health_pb2 as pb

        try:
            refreshed = self._ledger.refresh(request.reservation_id)
        except HealthError as exc:
            code = code_for(exc)
            return pb.ReservationResponse(
                granted=False, error_code=code, error_detail=summary_for(code)
            )
        return pb.ReservationResponse(
            granted=True, reservation=reservation_to_wire(refreshed, pb)
        )

    def GetCapabilityDrift(self, request, context):  # noqa: N802
        from .generated import health_pb2 as pb

        findings = check_capability_drift(config=self._config, metrics=self._metrics)
        return pb.DriftResponse(
            findings=[
                pb.CapabilityDriftFinding(
                    capability=f.capability,
                    python_version=f.python_version,
                    expected_path=f.expected_path,
                    actual_path=f.actual_path,
                    drifted=f.drifted,
                    detail=f.detail,
                )
                for f in findings
            ],
            any_drifted=any_drifted(findings),
        )

    def GetLiveDiagnostic(self, request, context):  # noqa: N802
        from .generated import health_pb2 as pb

        if request.service and request.operation:
            findings = (self._diagnostic.finding(request.service, request.operation),)
        else:
            findings = self._diagnostic.findings()
            if request.service:
                findings = tuple(f for f in findings if f.service == request.service)
        return pb.DiagnosticResponse(
            findings=[
                pb.LiveDiagnosticFinding(
                    service=f.service,
                    operation=f.operation,
                    baseline_class=f.baseline_class.value,
                    observed_class=f.observed_class.value,
                    sample_count=f.sample_count,
                    degraded=f.degraded,
                    detail=f.detail,
                )
                for f in findings
            ]
        )


class WatchdogServicer:
    """Implements `WatchdogService` (watchdog §7).

    Nothing here restarts anything. Watchdog detects and reports; Supervisor acts (watchdog
    §1), and the absence of a restart RPC on this surface is what makes that separation real
    rather than a convention someone could forget.
    """

    def __init__(
        self,
        *,
        kicks: KickRegistry | None = None,
        detector: TimeoutDetector | None = None,
    ) -> None:
        self._kicks = kicks or KickRegistry()
        self._detector = detector or TimeoutDetector(self._kicks)

    def Kick(self, request, context):  # noqa: N802
        from .generated import health_pb2 as pb

        try:
            beat = self._kicks.kick(
                request.service, request.instance_id, request.version_commit
            )
        except WatchdogError as exc:
            code = watchdog_code_for(exc)
            return pb.KickAck(accepted=False, error_code=code, error_detail=str(exc))
        return pb.KickAck(accepted=True, kicked_at=_iso(beat.kicked_at))

    def GetSilentServices(self, request, context):  # noqa: N802
        from .generated import health_pb2 as pb

        report = self._detector.check_for_silence()
        return pb.SilentServicesResponse(
            states=[
                pb.WatchdogState(
                    service=s.service,
                    instance_id=s.instance_id,
                    liveness=s.liveness.value,
                    last_kick_at=_iso(s.last_kick_at),
                    version_commit=s.version_commit,
                    silent_for_seconds=s.silent_for_seconds,
                    timeout_seconds=s.timeout_seconds,
                )
                for s in report.states
            ],
            silent_services=list(report.silent_services),
            checked_at=_iso(report.checked_at),
        )


def serve(
    address: str = DEFAULT_ADDRESS,
    *,
    profile: HardwareProfileReader | None = None,
    config: ConfigReader | None = None,
):
    """Start both servicers on one port. Returns the running server so a caller can stop it.

    One port for both services because Watchdog shares the parent's process
    (`docs/PROCESS_TOPOLOGY.md`) — a sub-API is not a separate deployment, and giving it its
    own port would imply otherwise to anything reading the config.

    Pass a `:0` port to bind an ephemeral one; the actually-bound address is attached to the
    returned server as `bound_address`. Windows reserves scattered ranges in the 50000s, so a
    fixed high port is not reliably bindable across machines.
    """
    import grpc

    from .generated import health_pb2_grpc as pb_grpc

    metrics = HealthMetricsCollector()
    ledger = ResourceLedger(profile=profile, metrics=metrics)
    kicks = KickRegistry()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_HealthServiceServicer_to_server(
        HealthServicer(ledger=ledger, config=config, metrics=metrics), server
    )
    pb_grpc.add_WatchdogServiceServicer_to_server(
        WatchdogServicer(kicks=kicks, detector=TimeoutDetector(kicks)), server
    )
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import sys

    # Real, live-found gap closed here: `serve()` always accepted a `profile` override,
    # but nothing here ever actually built one, so every real install's Health process
    # ran with the default `NoHardwareProfile()` regardless of what Setup API's own
    # `DetectHardware` had already found and persisted (`services/setup/hardware/
    # persistence.py`) -- every reservation against any real device rejected as
    # UNKNOWN_DEVICE forever, not because no GPU existed, but because nothing ever told
    # this process one did. `install_root=None` (a dev checkout, or a self-hosted install
    # before its first-run wizard) degrades to the same `NoHardwareProfile` behavior as
    # before -- not a regression, the same fail-closed default this ledger has always had.
    from common.install_paths import resolve_install_root
    from pathlib import Path as _Path

    from .resource_ledger import PublishedHardwareProfile

    install_root = resolve_install_root(_Path(__file__))
    hardware_profile = None
    if install_root is not None:
        from services.setup.hardware.persistence import read_hardware_profile

        hardware_profile = read_hardware_profile(install_root)

    addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
    srv = serve(addr, profile=PublishedHardwareProfile(hardware_profile))
    print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
    print(f"HealthService listening on {srv.bound_address}", file=sys.stderr)
    print(f"running under: {sys.executable} ({sys.version.split()[0]})", file=sys.stderr)
    from common.watchdog_client import ThreadedKicker
    kicker = ThreadedKicker('health')
    try:
        srv.wait_for_termination()
    finally:
        kicker.stop()

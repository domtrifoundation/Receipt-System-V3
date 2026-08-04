"""The `SupervisorServicer` gRPC servicer (`supervisor.proto`) — wires
`arbitration.ChannelArbitrator`, `rollback.rollback_channel`, `sleep_wake`'s
classification/state, `version_pins.VersionPinStore`, and `single_instance.
restart_service_on_version` to the wire surface §8 sketches. Deliberately local-only,
per that section's own framing — this is not meant to be reachable from the general
request path.

`ForceWake`/`PinServiceVersion` are Audit-logged (§11's own resolved "yes" for both) via
the same `GrpcAuditRecorder` shape `core/review_flagging/gateways.py` already
established this session — Audit's own closed operation vocabulary does not register
Supervisor's own operations yet, so a real call today returns `recorded=False,
error_code="UNKNOWN_ACTION"`, surfaced honestly rather than swallowed
(`docs/PRINCIPLES.md` §4.3), the identical shape that package's own gap already
documents.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from pathlib import Path

from .arbitration import ChannelArbitrator
from .available_versions import AvailableVersionsStore
from .contracts import ServiceSpec
from .instance_registry import InstanceRegistry
from .rollback import rollback_channel
from .single_instance import restart_service_on_version
from .sleep_wake.classification import policy_for
from .sleep_wake.state import SleepStateStore
from .version_pins import VersionPinStore

DEFAULT_ADDRESS = "127.0.0.1:50091"
DEFAULT_AUDIT_ADDRESS = "127.0.0.1:50058"

__all__ = ["DEFAULT_ADDRESS", "SupervisorServicer", "serve"]


async def _record_audit(operation: str, actor_user_id: str, *, address: str = DEFAULT_AUDIT_ADDRESS) -> None:
    """Best-effort — an audit-sink failure must never fail the operation it describes
    (`docs/PRINCIPLES.md` §4.4); this function itself never raises."""
    try:
        import grpc

        from core.audit.generated import audit_pb2 as pb
        from core.audit.generated import audit_pb2_grpc as pb_grpc

        async with grpc.aio.insecure_channel(address) as channel:
            stub = pb_grpc.AuditServiceStub(channel)
            await stub.RecordAction(pb.RecordActionRequest(operation=operation, actor_user_id=actor_user_id))
    except Exception:  # noqa: BLE001 - best-effort, see docstring
        pass


class SupervisorServicer:
    """Implements `SupervisorService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    #: Relative to the install root — every service's own real, dynamically-bound
    #: address, written as each one comes up. The real answer to "how does one service
    #: find another when ports are ephemeral, not fixed constants"
    #: (`common/blob_client.py`'s own Persistence lookup reads this same file).
    SERVICE_ADDRESSES_RELPATH = Path("supervisor") / "service_addresses.json"

    def __init__(
        self,
        install_root: Path | str,
        specs: dict[str, ServiceSpec],
        *,
        arbitrator: ChannelArbitrator | None = None,
        pins: VersionPinStore | None = None,
        sleep_state: SleepStateStore | None = None,
        available_versions: AvailableVersionsStore | None = None,
        instances: InstanceRegistry | None = None,
    ) -> None:
        self._install_root = Path(install_root)
        self._specs = specs
        self._arbitrator = arbitrator if arbitrator is not None else ChannelArbitrator(install_root)
        self._pins = pins if pins is not None else VersionPinStore(install_root)
        self._sleep_state = sleep_state if sleep_state is not None else SleepStateStore()
        self._available_versions = available_versions if available_versions is not None else AvailableVersionsStore(install_root)
        #: Every `(service_name, version)` instance this Supervisor process has itself
        #: launched via `StartVersion` — real, in-memory, this-process-lifetime state,
        #: same posture as `spawned_pids` below (`instance_registry.py`'s own docstring).
        self._instances = instances if instances is not None else InstanceRegistry()
        #: Every PID Supervisor has spawned via a boot — real cleanup on process exit
        #: needs this list; see `__main__.py`'s own docstring for why that ownership
        #: belongs here now, not the TUI's.
        self.spawned_pids: list[int] = []

    def _write_service_addresses(self, addresses: dict[str, str]) -> None:
        import json

        target = self._install_root / self.SERVICE_ADDRESSES_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(addresses, indent=2) + "\n", encoding="utf-8")

    async def GetActiveRelease(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import supervisor_pb2 as pb

        active = self._arbitrator.get_active(request.channel)
        if active is None:
            return pb.ActiveReleaseResponse(
                channel=request.channel, error_code="UNKNOWN_CHANNEL",
                error_detail=f"no active release on record for {request.channel!r}",
            )
        return pb.ActiveReleaseResponse(
            channel=active.channel, release_dir=str(active.release_dir), activated_at=active.activated_at.isoformat(),
        )

    async def TriggerRollback(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import supervisor_pb2 as pb

        specs = tuple(self._specs.values())
        result = await rollback_channel(request.channel, specs, self._arbitrator)
        return pb.RollbackResponse(
            channel=result.channel, reverted_to=str(result.reverted_to) if result.reverted_to else "",
            ok=result.ok, error_code=result.error_code, error_detail=result.error_detail,
        )

    async def GetSleepStatus(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import supervisor_pb2 as pb

        status = self._sleep_state.status_for(request.service_name)
        return pb.SleepStatusResponse(
            service_name=status.service_name, policy=status.policy.value, state=status.state.value,
            last_activity_at=status.last_activity_at.isoformat() if status.last_activity_at else "",
        )

    async def ForceWake(self, request, context=None):  # noqa: N802 - gRPC naming
        """§6.2's manual override — "wake this now, I need it." Audit-logged (§11)."""
        from .generated import supervisor_pb2 as pb

        spec = self._specs.get(request.service_name)
        if spec is None:
            return pb.WakeResponse(woke=False, error_code="UNKNOWN_SERVICE", error_detail=f"no spec registered for {request.service_name!r}")

        active = next(iter(self._arbitrator.all_active()), None)
        if active is None:
            return pb.WakeResponse(woke=False, error_code="NO_ACTIVE_RELEASE", error_detail="no channel has an active release yet")

        from .boot_sequence import launch_one

        result = await launch_one(spec, active.release_dir)
        await _record_audit("supervisor_force_wake", request.requested_by)
        if not result.ok:
            return pb.WakeResponse(woke=False, error_code="WAKE_FAILED", error_detail=result.error_detail)
        self._sleep_state.mark_active(request.service_name)
        return pb.WakeResponse(woke=True)

    async def PinServiceVersion(self, request, context=None):  # noqa: N802 - gRPC naming
        """§5.2's own surgical override, Audit-logged (§11)."""
        from .generated import supervisor_pb2 as pb

        pin = self._pins.set_pin(
            request.channel, request.service_name, request.pinned_version or None, pinned_by=request.pinned_by,
        )
        await _record_audit("supervisor_pin_service_version", request.pinned_by)
        if pin is None:
            return pb.ServiceVersionPinResponse(channel=request.channel, service_name=request.service_name)
        return pb.ServiceVersionPinResponse(
            channel=pin.channel, service_name=pin.service_name, pinned_version=pin.pinned_version or "",
            pinned_by=pin.pinned_by, pinned_at=pin.pinned_at.isoformat(),
        )

    async def ListServiceVersionPins(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import supervisor_pb2 as pb

        pins = self._pins.list_pins(request.channel or None)
        response = pb.PinListResponse()
        for pin in pins:
            response.pins.append(pb.ServiceVersionPinResponse(
                channel=pin.channel, service_name=pin.service_name, pinned_version=pin.pinned_version or "",
                pinned_by=pin.pinned_by, pinned_at=pin.pinned_at.isoformat(),
            ))
        return response

    async def StreamBootProgress(self, request, context=None):  # noqa: N802 - gRPC naming
        """The real fix for a real, live-found inversion: the TUI's own loading screen
        used to call `boot_many()` itself, which put Supervisor's own job in the wrong
        process — Interface API is a genuinely detachable *display* client, never the
        thing doing the starting. Supervisor calls `boot_many()` here, on its own real
        fleet registry (`fleet.build_fleet_specs`, resolved fresh against the active
        release for `request.channel`), and streams each service's own result as it
        happens — the TUI's `BootSequenceScreen` just renders what arrives.
        """
        import asyncio

        from .generated import supervisor_pb2 as pb

        channel = request.channel or "local"
        active = self._arbitrator.get_active(channel)
        if active is None:
            yield pb.BootProgressUpdate(
                boot_complete=True, boot_ok=False,
                error_detail=f"no active release recorded for channel {channel!r}",
            )
            return

        from .boot_sequence import boot_many
        from .fleet import build_fleet_specs

        specs = build_fleet_specs(active.release_dir)
        queue: asyncio.Queue = asyncio.Queue()
        _DONE = object()

        addresses: dict[str, str] = {}

        def on_result(result):
            queue.put_nowait(result)
            if result.pid is not None:
                self.spawned_pids.append(result.pid)
            if result.address:
                addresses[result.name] = result.address
                self._write_service_addresses(addresses)

        async def _run_boot():
            report = await boot_many(specs, active.release_dir, channel=channel, on_result=on_result)
            queue.put_nowait((_DONE, report))

        boot_task = asyncio.ensure_future(_run_boot())
        try:
            while True:
                item = await queue.get()
                if isinstance(item, tuple) and item and item[0] is _DONE:
                    report = item[1]
                    yield pb.BootProgressUpdate(
                        boot_complete=True, boot_ok=report.ok,
                        failed_services=list(report.failed_services),
                    )
                    break
                yield pb.BootProgressUpdate(
                    service_name=item.name, ok=item.ok, pid=item.pid or 0,
                    address=item.address, error_detail=item.error_detail,
                )
        finally:
            await boot_task

    async def RestartServiceOnVersion(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import supervisor_pb2 as pb

        if request.service_name not in ("interface_tui", "inference"):
            yield pb.RestartProgress(
                service_name=request.service_name, target_version=request.target_version,
                stage="failed", error_detail=f"{request.service_name!r} is not a single-instance service (only interface_tui/inference are, §5.3)",
            )
            return

        spec = self._specs.get(request.service_name)
        if spec is None:
            yield pb.RestartProgress(
                service_name=request.service_name, target_version=request.target_version,
                stage="failed", error_detail=f"no spec registered for {request.service_name!r}",
            )
            return

        releases_dir = self._install_root / "releases"
        async for progress in restart_service_on_version(
            request.service_name, request.target_version, releases_dir, spec, current_pid=None,
        ):
            yield pb.RestartProgress(
                service_name=progress.service_name, target_version=progress.target_version,
                stage=progress.stage, error_detail=progress.error_detail,
            )


    async def SetAvailableVersions(self, request, context=None):  # noqa: N802 - gRPC naming
        """The owner-set ceiling the webapp's own end-user version choice is bounded by
        (verbatim from the owning spec). Structurally truncated to one version for
        `interface_tui`/`inference` by `AvailableVersionsStore` itself, not by this
        handler — see that module's own docstring. Audit-logged, same posture as
        `PinServiceVersion`."""
        from .generated import supervisor_pb2 as pb

        versions = self._available_versions.set_available(request.channel, request.service_name, tuple(request.versions))
        await _record_audit("supervisor_set_available_versions", request.requested_by)
        return pb.AvailableVersionsResponse(channel=request.channel, service_name=request.service_name, versions=list(versions))

    async def ListAvailableVersions(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import supervisor_pb2 as pb

        entries = self._available_versions.list_all(request.channel)
        response = pb.AvailableVersionsListResponse()
        for service_name, versions in entries.items():
            response.entries.append(pb.AvailableVersionsResponse(
                channel=request.channel, service_name=service_name, versions=list(versions),
            ))
        return response

    def _resolve_spec(self, service_name: str) -> ServiceSpec | None:
        """`self._specs` is often empty (most callers construct `SupervisorServicer`
        without a pre-built registry — the real fleet is discovered fresh from whichever
        release is active, same as `StreamBootProgress` does). Falls back to building the
        fleet from the currently active release and matching by name; `import_path`/
        `serve_module` are stable across a service's own versions by construction (the
        module path doesn't change release to release), so a spec resolved against the
        *active* release is valid for launching any other version of that same service."""
        spec = self._specs.get(service_name)
        if spec is not None:
            return spec
        active = next(iter(self._arbitrator.all_active()), None)
        if active is None:
            return None
        from .fleet import build_fleet_specs

        for candidate in build_fleet_specs(active.release_dir):
            if candidate.name == service_name:
                return candidate
        return None

    async def StartVersion(self, request, context=None):  # noqa: N802 - gRPC naming
        """On-demand multi-version launch — real webapp demand starts a specific version
        rather than every available version being pre-booted. Refuses `interface_tui`/
        `inference` (`dynamic_start.ensure_version_running`'s own single-instance check);
        those two are restarted in place via `RestartServiceOnVersion` instead."""
        from .generated import supervisor_pb2 as pb

        spec = self._resolve_spec(request.service_name)
        if spec is None:
            return pb.StartVersionResponse(
                service_name=request.service_name, version=request.version, ok=False,
                error_detail=f"no spec found for {request.service_name!r} — is any release active?",
            )

        from .dynamic_start import ensure_version_running

        releases_dir = self._install_root / "releases"
        result = await ensure_version_running(self._instances, spec, request.version, releases_dir)
        if result.pid is not None:
            self.spawned_pids.append(result.pid)
        return pb.StartVersionResponse(
            service_name=request.service_name, version=request.version, ok=result.ok,
            pid=result.pid or 0, address=result.address, error_detail=result.error_detail,
        )

    async def ListRunningInstances(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import supervisor_pb2 as pb

        response = pb.RunningInstancesResponse()
        for service_name, version, result in self._instances.all():
            response.instances.append(pb.RunningInstance(
                service_name=service_name, version=version, ok=result.ok,
                pid=result.pid or 0, address=result.address,
            ))
        return response


async def serve(address: str = DEFAULT_ADDRESS, *, install_root: Path | str, specs: dict[str, ServiceSpec]):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring.

    Returns the running server with its own `servicer` attribute attached — `__main__.py`
    reads `server.servicer.spawned_pids` after the TUI exits, for real cleanup of
    whatever this run actually spawned (the boot happens inside `StreamBootProgress`,
    called by whichever TUI client connects, so this is the one place that list lives).
    """
    import grpc

    from .generated import supervisor_pb2_grpc

    servicer = SupervisorServicer(install_root, specs)
    server = grpc.aio.server()
    supervisor_pb2_grpc.add_SupervisorServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    server.servicer = servicer  # type: ignore[attr-defined]
    await server.start()
    return server

"""The `MigrationServicer` gRPC servicer (`migration.proto`) — the real assembly point
wiring `runner.MigrationRunner` (itself wrapping `registry.MigrationRegistry`) to the
wire surface. `CLAUDE.md`'s own "Known gap" section named this by name: a two-RPC
surface specified in the deep-dive with no `.proto` compiled at all.

Every behaviour these RPCs translate — chained N->N+1 walking, the fail-closed-on-a-gap
posture, idempotent re-runs — was already implemented and tested at the in-process layer
(`runner.py`, `registry.py`); this file is what was missing.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from .contracts import CURRENT_VERSIONS, MigrationResult, StructureKind
from .registry import MigrationRegistry, default_registry
from .runner import MigrationRunner

DEFAULT_ADDRESS = "127.0.0.1:50084"

__all__ = ["DEFAULT_ADDRESS", "MigrationServicer", "serve"]


def _step_result_to_pb(pb, result):
    return pb.StepResultInfo(
        kind=result.step.kind.value, from_version=result.step.from_version,
        to_version=result.step.to_version, description=result.step.description,
        outcome=result.outcome.value, started_at=result.started_at.isoformat(),
        finished_at=result.finished_at.isoformat(), error_code=result.error_code,
        error_detail=result.error_detail,
    )


def _migration_response(pb, result: MigrationResult):
    response = pb.MigrationResponse(
        structure_id=result.structure_id, kind=result.kind.value,
        from_version=result.from_version, reached_version=result.reached_version,
        target_version=result.target_version, error_code=result.error_code,
        error_detail=result.error_detail,
    )
    for step in result.steps:
        response.steps.append(_step_result_to_pb(pb, step))
    return response


class MigrationServicer:
    """Implements `MigrationService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(self, registry: MigrationRegistry | None = None, *, runner: MigrationRunner | None = None) -> None:
        self._runner = runner if runner is not None else MigrationRunner(registry or default_registry())

    async def RunMigration(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import migration_pb2 as pb

        try:
            kind = StructureKind(request.kind)
        except ValueError:
            return pb.MigrationResponse(
                structure_id=request.structure_id, kind=request.kind,
                error_code="UNKNOWN_STRUCTURE_KIND", error_detail=f"unknown kind {request.kind!r}",
            )

        target = request.target_version if request.target_version > 0 else None
        result = await self._runner.migrate(request.structure_id, kind, request.current_version, target)
        return _migration_response(pb, result)

    async def GetCurrentVersion(self, request, context=None):  # noqa: N802 - gRPC naming
        """This build's own target version for `kind` (`contracts.CURRENT_VERSIONS`) —
        not a specific structure's stored version, which Migration API does not itself
        persist (that column lives in whichever API owns the structure — Persistence for
        `database_schema`, Architect for `vendor_data`)."""
        from .generated import migration_pb2 as pb

        try:
            kind = StructureKind(request.kind)
        except ValueError:
            return pb.VersionResponse(
                kind=request.kind, error_code="UNKNOWN_STRUCTURE_KIND",
                error_detail=f"unknown kind {request.kind!r}",
            )
        return pb.VersionResponse(kind=kind.value, current_version=CURRENT_VERSIONS[kind])


async def serve(address: str = DEFAULT_ADDRESS, *, registry: MigrationRegistry | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import migration_pb2_grpc

    server = grpc.aio.server()
    migration_pb2_grpc.add_MigrationServiceServicer_to_server(MigrationServicer(registry), server)
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = await serve(addr)
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('migration')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())

"""The `TelemetreesServicer` gRPC servicer (`telemetrees.proto`) — the real assembly
point wiring `dependencies_warden.registry.TrackedDependencyRegistry` and the real
`docs/CHANGELOG.md` file (written by `dependencies_warden.changelog_surface.
ChangelogWriter`) to the wire surface. This API's own deep-dive §6 sketches this exact
two-RPC contract, but no `.proto` had been compiled and no servicer built.

`GetChangelog` returns the changelog file's own raw Markdown rather than a structured
entry list — this API does not maintain a separate structured store of past entries;
`ChangelogWriter` is the single writer and the file itself is the single source of truth.
"""

from __future__ import annotations

from pathlib import Path

from .dependencies_warden.registry import TrackedDependencyRegistry, default_registry
from .dependencies_warden.contracts import TrackedFactKind

DEFAULT_ADDRESS = "127.0.0.1:50088"

__all__ = ["DEFAULT_ADDRESS", "TelemetreesServicer", "serve"]


def _dependency_to_pb(pb, dependency):
    return pb.TrackedDependencyInfo(
        name=dependency.name, fact_kinds=[k.value for k in dependency.fact_kinds],
        upstream_issue_refs=list(dependency.upstream_issue_refs),
        source_deep_dive=dependency.source_deep_dive, notes=dependency.notes,
    )


class TelemetreesServicer:
    """Implements `TelemetreesService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        registry: TrackedDependencyRegistry | None = None,
        *,
        repo_root: Path | str | None = None,
    ) -> None:
        self._registry = registry if registry is not None else default_registry()
        self._repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]

    async def GetTrackedDependencies(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import telemetrees_pb2 as pb

        if request.fact_kind:
            try:
                kind = TrackedFactKind(request.fact_kind)
            except ValueError:
                return pb.TrackedDepsResponse(
                    error_code="UNKNOWN_FACT_KIND", error_detail=f"unknown fact kind {request.fact_kind!r}",
                )
            dependencies = self._registry.for_fact_kind(kind)
        else:
            dependencies = self._registry.all_dependencies()

        response = pb.TrackedDepsResponse()
        for dependency in dependencies:
            response.dependencies.append(_dependency_to_pb(pb, dependency))
        return response

    async def GetChangelog(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import telemetrees_pb2 as pb
        from .contracts import CHANGELOG_PATH

        path = self._repo_root / CHANGELOG_PATH
        try:
            markdown = path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError as exc:
            return pb.ChangelogResponse(error_code="CHANGELOG_UNREADABLE", error_detail=str(exc))
        return pb.ChangelogResponse(markdown=markdown)


async def serve(address: str = DEFAULT_ADDRESS, *, registry: TrackedDependencyRegistry | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import telemetrees_pb2_grpc

    server = grpc.aio.server()
    telemetrees_pb2_grpc.add_TelemetreesServiceServicer_to_server(TelemetreesServicer(registry), server)
    server.add_insecure_port(address)
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = await serve(addr)
        print(f"listening on {addr}", file=sys.stderr)
        await srv.wait_for_termination()

    asyncio.run(_main())

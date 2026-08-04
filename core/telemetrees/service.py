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
from .diagnostics.contracts import FiledIssueRecord
from .diagnostics.github_status_client import GitHubIssueStatusClient
from .diagnostics.ledger import FiledIssueLedger

DEFAULT_ADDRESS = "127.0.0.1:50088"

#: This project's own real repository — the one place `RecordFiledIssue`/
#: `ListFiledIssues` ever look, since this project only ever files issues against
#: itself, never a third party's repo.
DIAGNOSTICS_REPO_OWNER = "domtrifoundation"
DIAGNOSTICS_REPO_NAME = "Receipt-System-V3"

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
        install_root: Path | str | None = None,
    ) -> None:
        self._registry = registry if registry is not None else default_registry()
        self._repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
        #: `None` in a dev checkout — `GetOptIn`/`SetOptIn` report `known=false` rather
        #: than fabricating a value (`common/install_paths.resolve_install_root()`).
        self._install_root = Path(install_root) if install_root is not None else None

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

    def _resolve_install_root(self, request_install_root: str) -> Path | None:
        if request_install_root:
            return Path(request_install_root)
        return self._install_root

    async def GetOptIn(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import telemetrees_pb2 as pb
        from common.local_config_store import LocalConfigStore

        install_root = self._resolve_install_root(request.install_root)
        if install_root is None:
            return pb.OptInResponse(known=False)
        opt_in = LocalConfigStore(install_root, "telemetrees/config.json").get("opt_in", False)
        return pb.OptInResponse(opt_in=bool(opt_in), known=True)

    async def SetOptIn(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import telemetrees_pb2 as pb
        from common.local_config_store import LocalConfigStore

        install_root = self._resolve_install_root(request.install_root)
        if install_root is None:
            return pb.OptInResponse(known=False)
        LocalConfigStore(install_root, "telemetrees/config.json").set("opt_in", request.opt_in)
        return pb.OptInResponse(opt_in=request.opt_in, known=True)

    async def RecordFiledIssue(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import telemetrees_pb2 as pb

        install_root = self._resolve_install_root(request.install_root)
        if install_root is None:
            return pb.RecordFiledIssueResponse(known=False)
        FiledIssueLedger(install_root).record(FiledIssueRecord(
            fingerprint=request.fingerprint, issue_number=request.issue_number,
            url=request.url, title=request.title,
        ))
        return pb.RecordFiledIssueResponse(known=True)

    async def ListFiledIssues(self, request, context=None):  # noqa: N802 - gRPC naming
        """Real, live per-issue GitHub status — see `diagnostics/github_status_client.py`'s
        own docstring for why this is unauthenticated and read-only. Each record's live
        status is fetched fresh on every call rather than cached, so `checked_at` is
        always genuinely "just now," never a stale value presented as current."""
        from .generated import telemetrees_pb2 as pb

        install_root = self._resolve_install_root(request.install_root)
        if install_root is None:
            return pb.ListFiledIssuesResponse(known=False)

        records = FiledIssueLedger(install_root).list_all()
        client = GitHubIssueStatusClient(DIAGNOSTICS_REPO_OWNER, DIAGNOSTICS_REPO_NAME)
        response = pb.ListFiledIssuesResponse(known=True)
        for record in records:
            status = await client.get_status(record.issue_number)
            response.issues.append(pb.FiledIssueStatus(
                issue_number=record.issue_number, title=status.title or record.title,
                url=status.url or record.url, filed_at=record.filed_at.isoformat(),
                state=status.state, linked_pr_numbers=list(status.linked_pr_numbers),
                checked_at=status.checked_at.isoformat(), error_detail=status.error_detail,
            ))
        return response


async def serve(address: str = DEFAULT_ADDRESS, *, registry: TrackedDependencyRegistry | None = None, install_root: Path | str | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import telemetrees_pb2_grpc

    server = grpc.aio.server()
    telemetrees_pb2_grpc.add_TelemetreesServiceServicer_to_server(TelemetreesServicer(registry, install_root=install_root), server)
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        from common.install_paths import resolve_install_root

        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = await serve(addr, install_root=resolve_install_root(Path(__file__)))
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('telemetrees')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())

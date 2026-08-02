"""The `LogsService` gRPC servicer (§7) — the one surface clients see.

**Logs API runs as part of the core service cluster and is entirely indifferent to whether
any client is attached** (§1, and `docs/PRINCIPLES.md` §1.7). Interface's TUI is a gRPC
*client* of this service — one that can be closed, crash, or never be launched for a given
install, with zero effect on writing, rotation, or storage. Nothing in this module may ever
grow a dependency in the other direction: Logs API renders nothing and does not know
Interface exists.

The translation layer is deliberately thin. Everything the RPC does — the permission gate,
the index-or-scan decision, the filtering — belongs to `query.py`, so a future non-Python
client, the in-process caller, and this servicer all get the identical behaviour rather than
three implementations that could drift.

Errors are streamed as a terminal `LogQueryError` frame rather than raised as a gRPC status
(§4.1). A denied cross-user read is data the client can show, not an exception it has to
catch.
"""

from __future__ import annotations

from concurrent import futures
from datetime import datetime
from pathlib import Path

from .contracts import LogEntry, LogLevel, LogQuery, as_utc
from .index import LogIndex
from .metrics import LogsMetricsCollector
from .paths import default_log_root
from .query import AccessChecker, LogReader

DEFAULT_ADDRESS = "127.0.0.1:50058"
DEFAULT_LIMIT = 1000


def _parse_level(raw: str) -> LogLevel:
    """Unknown or empty defers to INFO rather than failing the query.

    A client built against a future version that added a level should get a usable stream,
    not a rejection — the graceful-degradation posture (§4.4) applied to the wire boundary.
    """
    try:
        return LogLevel(raw) if raw else LogLevel.INFO
    except ValueError:
        return LogLevel.INFO


def _parse_time(raw: str) -> datetime | None:
    """RFC 3339 in, timezone-aware out.

    A bound with no offset (`"2026-07-01"`, which `fromisoformat` accepts happily) is read
    as UTC rather than passed along naive — the whole read path compares it against
    timezone-aware entry timestamps, and a naive value reaching that comparison is a
    `TypeError` on a boundary that returns errors as data, never raises them (§4.1).
    """
    try:
        parsed = datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None
    return as_utc(parsed) if parsed is not None else None


def to_query(request) -> LogQuery:
    """Wire request -> `LogQuery`. Empty strings mean "unset", per proto3 semantics."""
    return LogQuery(
        run_id=request.run_id or None,
        user_id=request.user_id or None,
        service=request.service or None,
        min_level=_parse_level(request.min_level),
        since=_parse_time(request.since),
        until=_parse_time(request.until),
        limit=request.limit or DEFAULT_LIMIT,
        requesting_user_id=request.requesting_user_id or None,
    )


def to_record(entry: LogEntry, pb):
    """`LogEntry` -> wire frame, including the §3.1 style hint.

    The hint travels with the entry so a client never maintains its own severity-to-style
    table that could drift from what Logs defines its levels to mean. Translating the hint
    into an actual visual treatment stays entirely the client's business.
    """
    import json

    return pb.LogRecord(
        entry=pb.LogEntry(
            timestamp=entry.timestamp.isoformat(),
            run_id=entry.run_id or "",
            user_id=entry.user_id or "",
            service=entry.service,
            level=entry.level.value,
            message=entry.message,
            traceback=entry.traceback or "",
            suggested_style=entry.suggested_style,
            context_json=json.dumps(dict(entry.context), default=str),
        )
    )


class LogsServicer:
    """Implements `LogsService`. Registered by name, so importing the generated stubs is
    `serve()`'s business and this class stays importable without them."""

    def __init__(self, reader: LogReader) -> None:
        self._reader = reader

    def Query(self, request, context):  # noqa: N802 - gRPC method naming
        from .generated import logs_pb2 as pb

        result = self._reader.read(to_query(request))
        if not result.ok:
            yield pb.LogRecord(
                error=pb.LogQueryError(
                    error_code=result.error_code, error_detail=result.error_detail
                )
            )
            return
        for entry in result.entries:
            yield to_record(entry, pb)


def build_reader(
    root: Path | str | None = None,
    *,
    checker: AccessChecker | None = None,
    metrics: LogsMetricsCollector | None = None,
) -> LogReader:
    """Wire a reader over the real log root and its index.

    The index is constructed even if it cannot be opened — `LogIndex` degrades to
    unavailable on its own and `LogReader` falls back to scanning (§3.2), so there is
    deliberately no branch here deciding whether logs are queryable at all.
    """
    root = Path(root) if root else default_log_root()
    return LogReader(root, index=LogIndex(root=root), checker=checker, metrics=metrics)


def serve(
    address: str = DEFAULT_ADDRESS,
    reader: LogReader | None = None,
    *,
    root: Path | str | None = None,
    checker: AccessChecker | None = None,
):
    """Start the service. Returns the running server so a caller can stop it.

    Pass a `:0` port to bind an ephemeral one — the actually-bound address is attached to the
    returned server as `bound_address`. Windows reserves scattered ranges in the 50000s
    (`netsh interface ipv4 show excludedportrange tcp`), so a fixed high port is not reliably
    bindable across machines.
    """
    import grpc

    from .generated import logs_pb2_grpc as pb_grpc

    reader = reader or build_reader(root, checker=checker)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_LogsServiceServicer_to_server(LogsServicer(reader), server)
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import sys

    addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
    srv = serve(addr)
    print(f"LogsService listening on {addr}", file=sys.stderr)
    print(f"running under: {sys.executable} ({sys.version.split()[0]})", file=sys.stderr)
    srv.wait_for_termination()


__all__ = ["DEFAULT_ADDRESS", "LogsServicer", "build_reader", "serve", "to_query", "to_record"]

"""The `SearchQueryService` gRPC servicer (`v3-deepdive-21-search-query-api.md` §6, §8) — the
one surface clients see.

**Search/Query runs as part of the core service cluster and is entirely indifferent to
whether any client is attached** (`docs/PRINCIPLES.md` §1.7). This translation layer is
deliberately thin: every real decision — authorization, query construction, FTS5 escaping —
belongs to `permission_gate.py`, `structured_query.py`, and `fts_query.py`, so a future
non-Python client and an in-process caller both get identical behaviour instead of two
implementations that could drift, the same reasoning `core/logs/service.py` and
`core/groups/service.py` both state for their own servicers.

**Errors are data** (`docs/PRINCIPLES.md` §4.1): every response carries `error_code`/
`error_detail`; nothing here raises across the gRPC boundary.

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly as
`core/logs/service.py` and `core/health/service.py` do, so this package stays importable —
and its tests meaningful — on an interpreter with no `grpcio` wheel yet.
"""

from __future__ import annotations

import json
from concurrent import futures
from datetime import datetime
from decimal import Decimal

from core.auth.contracts import Role

from .contracts import AggregateQuery, GroupSearchQuery, SearchQuery
from .db import ReceiptDatabaseRegistry
from .metrics import SearchQueryMetricsCollector
from .permission_gate import SearchPermissionGate
from .structured_query import DenyAllGroupMembers, SearchExecutor

DEFAULT_ADDRESS = "127.0.0.1:50070"


def _parse_role(raw: str) -> Role:
    """Unknown or empty defers to the least-privileged role rather than failing the request
    — a client built against a future role value should get a correctly-scoped-down search,
    not a rejection (`docs/PRINCIPLES.md` §4.4's degrade-gracefully posture applied to the
    wire boundary, the same choice `core/logs/service.py`'s own `_parse_level` makes)."""
    try:
        return Role(raw) if raw else Role.CLIENT
    except ValueError:
        return Role.CLIENT


def _parse_time(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _parse_amount(value: float) -> Decimal | None:
    return Decimal(str(value)) if value else None


def to_search_query(request) -> SearchQuery:
    return SearchQuery(
        target_user_id=request.target_user_id,
        query_text=request.query_text,
        vendor_name=request.vendor_name,
        date_from=_parse_time(request.date_from),
        date_to=_parse_time(request.date_to),
        amount_min=_parse_amount(request.amount_min),
        amount_max=_parse_amount(request.amount_max),
        limit=request.limit or 100,
    )


def to_group_search_query(request) -> GroupSearchQuery:
    return GroupSearchQuery(
        group_id=request.group_id,
        query_text=request.query_text,
        vendor_name=request.vendor_name,
        date_from=_parse_time(request.date_from),
        date_to=_parse_time(request.date_to),
        amount_min=_parse_amount(request.amount_min),
        amount_max=_parse_amount(request.amount_max),
        limit=request.limit or 100,
    )


def to_aggregate_query(request) -> AggregateQuery:
    return AggregateQuery(
        target_user_id=request.target_user_id or None,
        group_id=request.group_id or None,
        date_from=_parse_time(request.date_from),
        date_to=_parse_time(request.date_to),
    )


def _result_entry(item, pb):
    return pb.SearchResultEntry(
        receipt_id=item.receipt_id,
        user_id=item.user_id,
        vendor_name=item.vendor_name,
        transaction_date=item.transaction_date.isoformat() if item.transaction_date else "",
        total_amount=str(item.total_amount) if item.total_amount is not None else "",
        currency=item.currency,
        fields_json=json.dumps(dict(item.fields), default=str, sort_keys=True),
    )


def to_search_response(result, pb):
    if not result.ok:
        return pb.SearchResponse(error_code=result.error_code, error_detail=result.error_detail)
    return pb.SearchResponse(
        results=[_result_entry(item, pb) for item in result.items],
        truncated=result.truncated,
        fts_degraded=result.fts_degraded,
    )


def to_aggregate_response(result, pb):
    if not result.ok:
        return pb.AggregateResponse(
            error_code=result.error_code, error_detail=result.error_detail
        )
    return pb.AggregateResponse(
        buckets=[
            pb.AggregateBucketEntry(
                vendor_name=b.vendor_name,
                receipt_count=b.receipt_count,
                total_amount=str(b.total_amount),
            )
            for b in result.buckets
        ]
    )


class SearchQueryServicer:
    """Implements `SearchQueryService`. Registered by name, so importing the generated stubs
    is `serve()`'s business and this class stays importable without them."""

    def __init__(self, executor: SearchExecutor) -> None:
        self._executor = executor

    async def Search(self, request, context):  # noqa: N802 - gRPC method naming
        from .generated import search_query_pb2 as pb

        result = await self._executor.search(
            to_search_query(request),
            requesting_user_id=request.requesting_user_id,
            requesting_role=_parse_role(request.requesting_role),
        )
        return to_search_response(result, pb)

    async def SearchGroup(self, request, context):  # noqa: N802
        from .generated import search_query_pb2 as pb

        result = await self._executor.search_group(
            to_group_search_query(request),
            requesting_user_id=request.requesting_user_id,
            requesting_role=_parse_role(request.requesting_role),
        )
        return to_search_response(result, pb)

    async def Aggregate(self, request, context):  # noqa: N802
        from .generated import search_query_pb2 as pb

        result = await self._executor.aggregate(
            to_aggregate_query(request),
            requesting_user_id=request.requesting_user_id,
            requesting_role=_parse_role(request.requesting_role),
        )
        return to_aggregate_response(result, pb)


def build_executor(
    *,
    top_level=None,
    gate: SearchPermissionGate | None = None,
    members=None,
) -> SearchExecutor:
    """Wire a `SearchExecutor` over the real per-user database registry.

    With no `gate`/`members` supplied, this is the fail-closed default: own-user reads only,
    no cross-group visibility (`DenyAllCrossUser`, `DenyAllGroupManager`,
    `DenyAllGroupMembers`) — wiring Auth and Groups in later means passing real adapters, not
    removing a permissive default someone forgot about (`docs/PRINCIPLES.md` §4.2).
    """
    registry = ReceiptDatabaseRegistry(top_level=top_level)
    return SearchExecutor(
        registry=registry,
        gate=gate or SearchPermissionGate(),
        members=members or DenyAllGroupMembers(),
        metrics=SearchQueryMetricsCollector(),
    )


def serve(
    address: str = DEFAULT_ADDRESS,
    *,
    executor: SearchExecutor | None = None,
    top_level=None,
):
    """Start the service. Returns the running server so a caller can stop it.

    Pass a `:0` port to bind an ephemeral one — the actually-bound address is attached to the
    returned server as `bound_address`, matching every other Core API's own `serve()`.
    """
    import grpc

    from .generated import search_query_pb2_grpc as pb_grpc

    executor = executor or build_executor(top_level=top_level)
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_SearchQueryServiceServicer_to_server(SearchQueryServicer(executor), server)
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    return server


__all__ = [
    "DEFAULT_ADDRESS",
    "SearchQueryServicer",
    "build_executor",
    "serve",
    "to_aggregate_query",
    "to_aggregate_response",
    "to_group_search_query",
    "to_search_query",
    "to_search_response",
]


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = serve(addr)
        await srv.start()
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('search_query')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())

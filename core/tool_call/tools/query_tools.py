"""Wraps Search/Query API's FTS5-backed structured search (`v3-deepdive-07-tool-call-
api.md` §3.2): "the actual V3 equivalent of 'look up rows by vendor/date/trans ID.'
Read-only, same category as V2's `excel_query` was." Replaces V2's `excel_query` — there
is no live, directly-queryable workbook in V3 at all (Excel is a generated export).

**Was a 0-byte scaffold until this session.**
"""

from __future__ import annotations

from collections.abc import Mapping

from common.frozen_dict import FrozenDict

from ..contracts import ToolCategory, ToolContext, ToolSpec
from ..registry import ToolRegistry

DEFAULT_SEARCH_QUERY_ADDRESS = "127.0.0.1:50070"

PERSISTENCE_QUERY_SPEC = ToolSpec(
    name="persistence_query",
    description=(
        "Search the calling user's own receipts by free text, vendor name, date range, or "
        "amount range. The V3 replacement for looking up rows in a workbook — there is no "
        "live, directly-queryable spreadsheet in this system."
    ),
    parameters_schema=FrozenDict({
        "type": "object",
        "properties": {
            "query_text": {"type": "string", "description": "Free-text search, FTS5-backed."},
            "vendor_name": {"type": "string"},
            "date_from": {"type": "string", "description": "RFC 3339, inclusive lower bound."},
            "date_to": {"type": "string", "description": "RFC 3339, inclusive upper bound."},
            "limit": {"type": "integer", "description": "Maximum results. Defaults to the server default."},
        },
    }),
    category=ToolCategory.READ_ONLY,
)


def _is_search_query_available(address: str = DEFAULT_SEARCH_QUERY_ADDRESS) -> bool:
    try:
        import grpc

        with grpc.insecure_channel(address) as channel:
            grpc.channel_ready_future(channel).result(timeout=1.0)
        return True
    except Exception:  # noqa: BLE001 - unreachable means unavailable
        return False


def persistence_query(arguments: FrozenDict, context: ToolContext, *, address: str = DEFAULT_SEARCH_QUERY_ADDRESS) -> Mapping:
    """Scoped to the calling user's own receipts (`context.user_id`) — this tool has no
    cross-user search shape at all; `SearchGroup` is a different RPC this tool does not
    expose, matching §1's "wraps the mechanism, doesn't invent a new one" boundary."""
    import grpc

    from core.search_query.generated import search_query_pb2 as pb
    from core.search_query.generated import search_query_pb2_grpc as pb_grpc

    with grpc.insecure_channel(address) as channel:
        stub = pb_grpc.SearchQueryServiceStub(channel)
        response = stub.Search(pb.SearchRequest(
            query_text=arguments.get("query_text", "") or "",
            target_user_id=context.user_id,
            date_from=arguments.get("date_from", "") or "",
            date_to=arguments.get("date_to", "") or "",
            vendor_name=arguments.get("vendor_name", "") or "",
            limit=int(arguments.get("limit", 0) or 0),
            requesting_user_id=context.user_id, requesting_role="client",
        ), timeout=15.0)

    if response.error_code:
        raise RuntimeError(f"{response.error_code}: {response.error_detail}")

    return {
        "truncated": response.truncated,
        "fts_degraded": response.fts_degraded,
        "results": [
            {
                "receipt_id": r.receipt_id, "vendor_name": r.vendor_name,
                "transaction_date": r.transaction_date, "total_amount": r.total_amount,
                "currency": r.currency,
            }
            for r in response.results
        ],
    }


def register_query_tools(registry: ToolRegistry, *, address: str = DEFAULT_SEARCH_QUERY_ADDRESS) -> None:
    """The real registration entry point `service.py`'s assembly calls."""
    registry.register(
        PERSISTENCE_QUERY_SPEC,
        lambda arguments, context: persistence_query(arguments, context, address=address),
        available=lambda: _is_search_query_available(address),
    )


__all__ = ["PERSISTENCE_QUERY_SPEC", "persistence_query", "register_query_tools"]

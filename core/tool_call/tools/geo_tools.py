"""Wraps Geo/Address API (`v3-deepdive-07-tool-call-api.md` §3.1: "`geocode_place` ->
Geo/Address API directly, same capability, same 'only offer the tool if a provider is
actually configured' pattern worth keeping (§3.3)").

**Was a 0-byte scaffold until this session** — a real, complete gap: `registry.py`'s own
`RegisteredTool.available` seam and `dispatch.py`'s full enforcement/audit/timeout
pipeline were built and tested, but none of the five tool modules the deep-dive's own §2
package layout names had a single line of logic in them, so there was nothing to actually
register.

`geocode_place` is `READ_ONLY` — it corroborates candidate address strings against
Geo/Address's own multi-provider registry and returns the result; it never writes
anything.
"""

from __future__ import annotations

from collections.abc import Mapping

from common.frozen_dict import FrozenDict

from ..contracts import ToolCategory, ToolContext, ToolSpec
from ..registry import ToolRegistry

DEFAULT_GEO_ADDRESS_ADDRESS = "127.0.0.1:50062"

GEOCODE_PLACE_SPEC = ToolSpec(
    name="geocode_place",
    description=(
        "Geocode one or more OCR-read candidate address strings for a receipt, corroborated "
        "across every configured provider, and return the normalized address with an "
        "agreement/confidence verdict."
    ),
    parameters_schema=FrozenDict({
        "type": "object",
        "properties": {
            "candidate_strings": {
                "type": "array", "items": {"type": "string"},
                "description": "OCR-read address candidates, highest-confidence first.",
            },
            "vendor_name_hint": {
                "type": "string",
                "description": "The OCR-read vendor name, for the reverse cross-corroboration pass. Optional.",
            },
            "country_code": {"type": "string", "description": "Defaults to PH if omitted."},
        },
        "required": ["candidate_strings"],
    }),
    category=ToolCategory.READ_ONLY,
)


def _is_geo_address_available(address: str = DEFAULT_GEO_ADDRESS_ADDRESS) -> bool:
    """§3.3's "only offer the tool if a provider is actually configured" pattern — a
    real, live reachability probe against Geo/Address's own servicer, not a hardcoded
    `True`. `is_available` degrading to `False` on any failure is `RegisteredTool`'s own
    documented contract (`registry.py`), never a crash."""
    try:
        import grpc

        with grpc.insecure_channel(address) as channel:
            grpc.channel_ready_future(channel).result(timeout=1.0)
        return True
    except Exception:  # noqa: BLE001 - unreachable means unavailable, per registry.py's contract
        return False


def geocode_place(arguments: FrozenDict, context: ToolContext, *, address: str = DEFAULT_GEO_ADDRESS_ADDRESS) -> Mapping:
    """The real handler — a thin, synchronous gRPC call (matching `RegisteredTool.handler`'s
    own synchronous signature; `dispatch.py` runs every handler on a thread-pool future)."""
    import grpc

    from core.geo_address.generated import geo_address_pb2 as pb
    from core.geo_address.generated import geo_address_pb2_grpc as pb_grpc

    candidates = list(arguments.get("candidate_strings", ()))
    with grpc.insecure_channel(address) as channel:
        stub = pb_grpc.GeoAddressServiceStub(channel)
        response = stub.Geocode(pb.GeocodeRequest(
            candidate_strings=candidates,
            country_code=arguments.get("country_code", "") or "",
            vendor_name_hint=arguments.get("vendor_name_hint", "") or "",
        ), timeout=15.0)

    if response.error_code:
        raise RuntimeError(f"{response.error_code}: {response.error_detail}")

    result = response.result
    return {
        "agreement": result.agreement,
        "confidence": result.confidence,
        "normalized_address": result.normalized_address.formatted if result.HasField("normalized_address") else None,
        "city": result.normalized_address.city if result.HasField("normalized_address") else "",
        "province": result.normalized_address.province if result.HasField("normalized_address") else "",
        "conflict": result.conflict,
        "conflict_detail": result.conflict_detail,
        "vendor_name_discrepancy": result.vendor_name_discrepancy,
    }


def register_geo_tools(registry: ToolRegistry, *, address: str = DEFAULT_GEO_ADDRESS_ADDRESS) -> None:
    """The real registration entry point `service.py`'s assembly calls."""
    registry.register(
        GEOCODE_PLACE_SPEC,
        lambda arguments, context: geocode_place(arguments, context, address=address),
        available=lambda: _is_geo_address_available(address),
    )


__all__ = ["GEOCODE_PLACE_SPEC", "geocode_place", "register_geo_tools"]

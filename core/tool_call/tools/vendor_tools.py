"""Wraps Architect API's registry (read) and `temporal_learning` (write) — `v3-deepdive-
07-tool-call-api.md` §3.1: "`lookup_vendor_canon` ... -> Architect API's registry (read
side). The *write* equivalent (`remember_vendor` ...) -> Architect's `temporal_learning`
submodule, which already owns exactly this contribution/learning mechanism — these tools
become thin wrappers around a mechanism that already exists, not new logic."

**Was a 0-byte scaffold until this session.**

`remember_vendor` is `MUTATING_STAGED`, never `MUTATING_DIRECT` (§4): it stages a proposed
new/corrected corporation into Architect's own moderation queue (LLM-prescreen -> staff
review -> merge) via `SubmitContribution` — the exact same RPC `core/architect/service.py`
built this session — and self-applies during automated processing precisely because the
safety gate is downstream and asynchronous, never a live confirmation with nobody there
to answer it.
"""

from __future__ import annotations

from collections.abc import Mapping

from common.frozen_dict import FrozenDict

from ..contracts import ToolCategory, ToolContext, ToolSpec
from ..registry import ToolRegistry

DEFAULT_ARCHITECT_ADDRESS = "127.0.0.1:50060"

LOOKUP_VENDOR_CANON_SPEC = ToolSpec(
    name="lookup_vendor_canon",
    description=(
        "Search Architect's vendor directory for a corporation by name, alias, or TIN. "
        "Exact-on-normalized matching only — this does not fuzzy-match noisy OCR text."
    ),
    parameters_schema=FrozenDict({
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "A vendor name, alias, or TIN to search for."},
            "limit": {"type": "integer", "description": "Maximum results. Defaults to 25."},
        },
        "required": ["query"],
    }),
    category=ToolCategory.READ_ONLY,
)

REMEMBER_VENDOR_SPEC = ToolSpec(
    name="remember_vendor",
    description=(
        "Propose a new or corrected vendor corporation (name, TIN, category) for staff "
        "review. Stages a contribution into Architect's moderation queue; never writes "
        "directly to the shared vendor directory."
    ),
    parameters_schema=FrozenDict({
        "type": "object",
        "properties": {
            "corporation_id": {
                "type": "string",
                "description": "Empty for a genuinely new corporation; set to correct an existing one.",
            },
            "name": {"type": "string"},
            "corporate_tin": {"type": "string"},
        },
        "required": ["name"],
    }),
    category=ToolCategory.MUTATING_STAGED,
)


def _is_architect_available(address: str = DEFAULT_ARCHITECT_ADDRESS) -> bool:
    try:
        import grpc

        with grpc.insecure_channel(address) as channel:
            grpc.channel_ready_future(channel).result(timeout=1.0)
        return True
    except Exception:  # noqa: BLE001 - unreachable means unavailable
        return False


def lookup_vendor_canon(arguments: FrozenDict, context: ToolContext, *, address: str = DEFAULT_ARCHITECT_ADDRESS) -> Mapping:
    import grpc

    from core.architect.generated import architect_pb2 as pb
    from core.architect.generated import architect_pb2_grpc as pb_grpc

    with grpc.insecure_channel(address) as channel:
        stub = pb_grpc.ArchitectServiceStub(channel)
        response = stub.SearchVendorDirectory(pb.VendorSearchRequest(
            query=arguments.get("query", ""), user_id=context.user_id,
            limit=int(arguments.get("limit", 0) or 25),
        ), timeout=15.0)

    if response.error_code:
        raise RuntimeError(f"{response.error_code}: {response.error_detail}")

    return {
        "records": [
            {
                "corporation_id": r.corporation_id, "name": r.name,
                "corporate_tin": r.corporate_tin, "layer": r.layer,
                "category_code": r.category_code, "branch_count": r.branch_count,
            }
            for r in response.records
        ]
    }


def remember_vendor(arguments: FrozenDict, context: ToolContext, *, address: str = DEFAULT_ARCHITECT_ADDRESS) -> Mapping:
    import grpc

    from core.architect.generated import architect_pb2 as pb
    from core.architect.generated import architect_pb2_grpc as pb_grpc

    change = {"name": arguments.get("name", "")}
    if arguments.get("corporate_tin"):
        change["corporate_tin"] = arguments["corporate_tin"]

    with grpc.insecure_channel(address) as channel:
        stub = pb_grpc.ArchitectServiceStub(channel)
        response = stub.SubmitContribution(pb.ContributionRequest(
            contributor=f"tool_call:{context.calling_api}", target_entity_type="corporation",
            target_entity_id=arguments.get("corporation_id", "") or "",
            proposed_change=change, staff_authored=False,
        ), timeout=15.0)

    if response.error_code:
        raise RuntimeError(f"{response.error_code}: {response.error_detail}")

    return {
        "contribution_id": response.contribution.contribution_id,
        "staff_review_status": response.contribution.staff_review_status,
        "merged": response.contribution.merged,
    }


def register_vendor_tools(registry: ToolRegistry, *, address: str = DEFAULT_ARCHITECT_ADDRESS) -> None:
    """The real registration entry point `service.py`'s assembly calls."""
    available = lambda: _is_architect_available(address)  # noqa: E731
    registry.register(
        LOOKUP_VENDOR_CANON_SPEC,
        lambda arguments, context: lookup_vendor_canon(arguments, context, address=address),
        available=available,
    )
    registry.register(
        REMEMBER_VENDOR_SPEC,
        lambda arguments, context: remember_vendor(arguments, context, address=address),
        available=available,
    )


__all__ = [
    "LOOKUP_VENDOR_CANON_SPEC",
    "REMEMBER_VENDOR_SPEC",
    "lookup_vendor_canon",
    "register_vendor_tools",
    "remember_vendor",
]

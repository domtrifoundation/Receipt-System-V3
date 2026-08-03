"""Wraps Persistence's normal write path directly (`v3-deepdive-07-tool-call-api.md`
§3.2): "every tool-initiated write is automatically Historian-logged the same as any
other write in the system." `persistence_write_field` is `MUTATING_STAGED` per §4 — the
existing gate it self-applies into is Persistence's own Historian-backed, atomic write
path (`core/persistence/grpc_servicer.py`'s `SaveReceipt`), not a human confirmation step.

**Was a 0-byte scaffold until this session.**

**§9's own resolved scope, applied literally: "a narrower, explicitly-enumerated set of
writable fields, even within `MUTATING_STAGED`."** `WRITABLE_FIELDS` below is that
enumeration — the same discipline Task Scheduler's own curated allowlist and Review/
Flagging's `FLAG_TYPE_EDIT_FIELD` table already apply elsewhere in this project: "any
field a schema permits" is exactly the open-ended surface this project avoids, and there
is no reason this tool should be the exception.
"""

from __future__ import annotations

from collections.abc import Mapping

from common.frozen_dict import FrozenDict

from ..contracts import ToolCategory, ToolContext, ToolSpec
from ..registry import ToolRegistry

DEFAULT_PERSISTENCE_ADDRESS = "127.0.0.1:50072"

#: The narrow, explicit set of `Receipt` fields this tool may ever write — §9's own
#: resolved scope. A field not in this set is not writable through this tool at all,
#: full stop; there is no fallback path.
WRITABLE_FIELDS: frozenset[str] = frozenset(
    {"vendor_name", "currency", "total_amount", "vat_amount", "transaction_date"}
)

PERSISTENCE_WRITE_FIELD_SPEC = ToolSpec(
    name="persistence_write_field",
    description=(
        "Correct one field on one of the calling user's own receipts, through Persistence's "
        "normal Historian-logged write path. Only a narrow, enumerated set of fields may be "
        f"written this way: {', '.join(sorted(WRITABLE_FIELDS))}."
    ),
    parameters_schema=FrozenDict({
        "type": "object",
        "properties": {
            "receipt_id": {"type": "string"},
            "field": {"type": "string", "enum": sorted(WRITABLE_FIELDS)},
            "new_value": {"type": "string"},
        },
        "required": ["receipt_id", "field", "new_value"],
    }),
    category=ToolCategory.MUTATING_STAGED,
)


def _is_persistence_available(address: str = DEFAULT_PERSISTENCE_ADDRESS) -> bool:
    try:
        import grpc

        with grpc.insecure_channel(address) as channel:
            grpc.channel_ready_future(channel).result(timeout=1.0)
        return True
    except Exception:  # noqa: BLE001 - unreachable means unavailable
        return False


def persistence_write_field(arguments: FrozenDict, context: ToolContext, *, address: str = DEFAULT_PERSISTENCE_ADDRESS) -> Mapping:
    """A real read-modify-write over `GetReceipt`/`SaveReceipt` — matching
    `core/review_flagging/gateways.py::GrpcPersistenceWriteGateway`'s own composition,
    since `persistence.proto` still has no dedicated field-level `ApplyEdit` RPC."""
    field = arguments.get("field", "")
    if field not in WRITABLE_FIELDS:
        raise ValueError(f"{field!r} is not a writable field through this tool")

    import grpc

    from core.persistence.generated import persistence_pb2 as pb
    from core.persistence.generated import persistence_pb2_grpc as pb_grpc

    receipt_id = arguments.get("receipt_id", "")
    new_value = arguments.get("new_value", "")

    with grpc.insecure_channel(address) as channel:
        stub = pb_grpc.PersistenceServiceStub(channel)
        fetched = stub.GetReceipt(pb.GetReceiptRequest(user_id=context.user_id, receipt_id=receipt_id), timeout=15.0)
        if fetched.error_code:
            raise RuntimeError(f"{fetched.error_code}: {fetched.error_detail}")

        msg = fetched.receipt
        setattr(msg, field, new_value)

        saved = stub.SaveReceipt(pb.SaveReceiptRequest(
            receipt=msg, actor=f"llm:{context.calling_api}",
        ), timeout=15.0)

    if saved.error_code:
        raise RuntimeError(f"{saved.error_code}: {saved.error_detail}")

    return {"receipt_id": saved.receipt_id, "historian_event_id": saved.historian_event_id}


def register_persistence_write_tools(registry: ToolRegistry, *, address: str = DEFAULT_PERSISTENCE_ADDRESS) -> None:
    """The real registration entry point `service.py`'s assembly calls."""
    registry.register(
        PERSISTENCE_WRITE_FIELD_SPEC,
        lambda arguments, context: persistence_write_field(arguments, context, address=address),
        available=lambda: _is_persistence_available(address),
    )


__all__ = ["PERSISTENCE_WRITE_FIELD_SPEC", "WRITABLE_FIELDS", "persistence_write_field", "register_persistence_write_tools"]

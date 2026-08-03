"""Receipt -> accounting-software expense/bill record (deep-dive §1's own stated
boundary: "never maintains a second, parallel vendor concept of its own" — this module
reads Persistence's own canonical `Receipt` and Architect's own temporal_learning
Corporation/Franchiser/Branch structure, never invents its own vendor identity).

**Field mapping completeness is explicitly open research** (deep-dive §10) — "genuinely
needs real research against each platform's own current, actual schema, not something
resolvable by reasoning alone." What's built here is the honest, real subset the deep-dive
itself specifies with confidence (vendor name, date, amount, currency) plus the
extensibility point (`MappedRecord.extra`) for whatever a real schema pass adds later —
not a claim that every QuickBooks/Xero field a real integration eventually wants is
covered.
"""

from __future__ import annotations

from decimal import Decimal

from .contracts import MappedRecord
from .errors import MappingFailed

__all__ = ["map_receipt_to_record"]


def map_receipt_to_record(receipt, vendor_display_name: str | None = None) -> MappedRecord:
    """`receipt` is `core.persistence.contracts.Receipt` — not imported by type here to
    avoid this package taking a hard dependency on Persistence's own module just for a
    type hint; every field this function actually reads is a plain attribute access, the
    same duck-typed-boundary posture already used at a few other cross-API seams in this
    project where a full Protocol felt like more ceremony than the read actually needs.

    `vendor_display_name` overrides `receipt.vendor_name` when the caller has already
    resolved a real Corporation/Franchiser/Branch record (deep-dive §1) — this function
    itself never queries temporal_learning; that resolution is `sync_engine.py`'s own job,
    keeping this function a pure, easily-tested translation with no I/O of its own.

    Raises `MappingFailed` for a receipt genuinely missing what a push needs (no vendor
    name at all, no total amount) — a data-quality gap, not a provider-side failure.
    """
    vendor_name = vendor_display_name or receipt.vendor_name
    if not vendor_name:
        raise MappingFailed(f"receipt {receipt.receipt_id!r} has no vendor name to push")
    if receipt.total_amount is None:
        raise MappingFailed(f"receipt {receipt.receipt_id!r} has no total amount to push")
    if receipt.transaction_date is None:
        raise MappingFailed(f"receipt {receipt.receipt_id!r} has no transaction date to push")

    total = receipt.total_amount
    if not isinstance(total, Decimal):
        total = Decimal(str(total))

    return MappedRecord(
        receipt_id=receipt.receipt_id,
        vendor_name=vendor_name,
        transaction_date=receipt.transaction_date,
        total_amount=str(total),
        currency=receipt.currency,
        category=receipt.fields.get("category") if hasattr(receipt, "fields") else None,
    )

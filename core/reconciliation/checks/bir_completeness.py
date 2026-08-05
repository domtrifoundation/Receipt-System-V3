"""§4.7 — the BIR completeness check.

Required-field presence per BIR documentation requirements: TIN, official receipt / sales
invoice number, date, and a VAT breakdown. §4.7 is explicit that this is "a straightforward
presence/format check, **distinct from VAT math's *correctness* check**".

That distinction is the whole reason this check is its own file rather than a branch inside
`vat_math.py`. The two answer different questions about the same fields and a filer needs both
answers separately: a receipt missing its VAT breakdown entirely is not BIR-compliant
documentation regardless of whether any arithmetic would have reconciled, and a receipt with a
complete breakdown that does not add up is compliant-looking documentation with a real error in
it. Folding them together would report one finding where there are two, and the remedy for each
is different — one needs a better scan or a better receipt, the other needs the numbers checked.

A zero-rated or VAT-exempt receipt still needs its VAT fields *present* (stating zero), because
the BIR requirement is that the breakdown be shown, not that it be non-zero.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import FLAG_TYPES, ReceiptSnapshot, Severity
from .base import flagged, passed

CHECK_NAME = "bir_completeness"

#: The fields BIR requires a receipt to carry, as data rather than as a chain of `if`s — a
#: required field that lives only in control flow cannot be enumerated, reported to a human, or
#: reviewed as a list. `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1.
REQUIRED_FIELDS: FrozenDict = FrozenDict(
    {
        "vendor_tin": "vendor TIN",
        "receipt_number": "official receipt / sales invoice number",
        "transaction_date": "transaction date",
        "subtotal_centavos": "VAT-exclusive amount",
        "vat_centavos": "VAT amount",
        "total_centavos": "VAT-inclusive total",
    }
)


def missing_fields(snapshot: ReceiptSnapshot) -> tuple[str, ...]:
    """Which required fields this receipt does not carry.

    An empty string and a `None` both count as absent; a zero does **not**. A zero-rated
    receipt's VAT amount is legitimately `0` and is present — treating falsiness as absence
    would report every zero-rated receipt in the country as incomplete documentation.
    """
    absent: list[str] = []
    for field_name, label in REQUIRED_FIELDS.items():
        value = getattr(snapshot, field_name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            absent.append(label)
    return tuple(absent)


class BirCompletenessCheck:
    """§4.7, as a registry entry."""

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        absent = missing_fields(snapshot)
        if absent:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["bir_completeness"],
                Severity.HIGH,
                f"missing BIR-required field(s): {', '.join(absent)}",
                FrozenDict({"missing": absent}),
            )
        return passed(CHECK_NAME, "every BIR-required field is present")


__all__ = ["CHECK_NAME", "BirCompletenessCheck", "REQUIRED_FIELDS", "missing_fields"]

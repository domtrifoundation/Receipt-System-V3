"""§4.5 — the semantic duplicate check, a gap neither Ingestion's nor Background Workers' dedup covers.

Ingestion's content-hash dedup catches exact byte-duplicate uploads. It does **not** catch two
genuinely different image files — a different photo, a different compression — representing the
*same real-world transaction*. §4.5 names the common case precisely: someone re-uploading the
same physical receipt through a different channel, or scanning it twice by accident.

**Deliberately not image similarity.** §4.5 says so directly, and both the Background Workers
and Preprocessing deep-dives already flag image similarity as a genuinely open, harder problem.
This is a fuzzy match across a small set of high-signal fields.

**§8 resolves the field set and the threshold**: vendor, same-day date, and amount within 1%
"allowing for rounding/tax-display differences" — conservative on purpose, and "never
auto-merged regardless of threshold, only ever flagged for review". That last clause is
`docs/PRINCIPLES.md` §4.3: two receipts that look like duplicates might be two genuine
transactions at the same shop on the same day for the same price, which is completely ordinary
at a convenience store. A human decides.

The receipt number is used as a **tiebreaker in both directions**, and that asymmetry is the
sharpest thing in this file: two receipts with *different* extracted receipt numbers are
positively distinct transactions and are never flagged, however well their other fields match.
Without that, a lunch bought twice on the same day at the same price is a duplicate every time.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import (
    DuplicateCandidateSource,
    FLAG_TYPES,
    ReceiptSnapshot,
    Severity,
)
from .base import flagged, inconclusive, passed

CHECK_NAME = "semantic_duplicate"

#: §8's "within 1%, allowing for rounding/tax-display differences", in basis points so the
#: comparison stays in exact integer arithmetic against centavo amounts.
AMOUNT_TOLERANCE_BASIS_POINTS: int = 100


def amounts_match(a: int, b: int) -> bool:
    """Whether two centavo amounts agree within §8's 1% tolerance.

    Integer arithmetic throughout, against the larger of the two so the relation is symmetric —
    `a` within 1% of `b` and `b` within 1% of `a` must be the same question, or whether two
    receipts are duplicates would depend on which one was looked at first.
    """
    if a == b:
        return True
    scale = max(abs(a), abs(b))
    return abs(a - b) * 10_000 <= AMOUNT_TOLERANCE_BASIS_POINTS * scale


def looks_like_same_transaction(left: ReceiptSnapshot, right: ReceiptSnapshot) -> bool:
    """§8's field set: same vendor, same day, amount within 1% — with the receipt-number veto.

    The veto is not symmetric with the match. Two *different* receipt numbers prove two
    transactions; two *absent* receipt numbers prove nothing either way and leave the other
    fields to decide.
    """
    if left.receipt_id == right.receipt_id:
        return False
    if not left.vendor_name or left.vendor_name.casefold() != right.vendor_name.casefold():
        return False
    if left.transaction_date is None or left.transaction_date != right.transaction_date:
        return False
    if left.total_centavos is None or right.total_centavos is None:
        return False
    if not amounts_match(left.total_centavos, right.total_centavos):
        return False

    left_number = left.receipt_number.strip()
    right_number = right.receipt_number.strip()
    if left_number and right_number and left_number != right_number:
        return False
    return True


class SemanticDuplicateCheck:
    """§4.5, as a registry entry. Reads `duplicate_candidates` from the run context."""

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        source = context.get("duplicate_candidates")
        if not isinstance(source, DuplicateCandidateSource):
            return inconclusive(
                CHECK_NAME, "no duplicate-candidate source supplied for this run"
            )

        if snapshot.transaction_date is None or snapshot.total_centavos is None:
            return inconclusive(
                CHECK_NAME,
                "§8's field set needs a transaction date and a total; this receipt has neither "
                "or only one",
            )

        candidates = await source.candidates_for(snapshot)
        matches = tuple(
            candidate.receipt_id
            for candidate in candidates
            if looks_like_same_transaction(snapshot, candidate)
        )

        if matches:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["semantic_duplicate"],
                Severity.MEDIUM,
                (
                    f"matches {len(matches)} other receipt(s) on vendor, date and amount: "
                    f"{', '.join(matches)} — flagged for review, never merged"
                ),
                FrozenDict({"candidate_ids": matches}),
            )

        return passed(CHECK_NAME, f"no semantic duplicate among {len(candidates)} candidates")


__all__ = [
    "AMOUNT_TOLERANCE_BASIS_POINTS",
    "CHECK_NAME",
    "SemanticDuplicateCheck",
    "amounts_match",
    "looks_like_same_transaction",
]

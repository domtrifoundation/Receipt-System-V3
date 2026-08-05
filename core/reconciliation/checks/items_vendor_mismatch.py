"""§4.6 — the items-versus-vendor mismatch check.

§4.6's own example: "a receipt whose items strongly suggest one vendor category (e.g. grocery
items) but whose matched vendor is categorized differently is a real, catchable inconsistency."
The complement of `vendor_group_mismatch.py` — that one compares two pieces of registry metadata
about the vendor, this one compares registry metadata against what was actually bought.

**"Strongly suggest" is the load-bearing phrase, and it is why a majority is not enough here.**
A receipt from a supermarket legitimately contains a hardware item; one mismatched line is not a
finding. The threshold is deliberately high — a clear preponderance of items pointing somewhere
other than the vendor's own category — because this check's false positives land on ordinary
mixed baskets, which are the common case rather than the exception.

`docs/PRINCIPLES.md` §4.3: surfaced, never auto-recategorised. The items might be miscategorised
rather than the vendor; nothing here can tell which, and guessing would silently rewrite a
vendor's category on the strength of one shopping trip.
"""

from __future__ import annotations

from collections import Counter

from common.frozen_dict import FrozenDict

from ..contracts import FLAG_TYPES, ReceiptSnapshot, Severity
from .base import flagged, inconclusive, passed

CHECK_NAME = "items_vendor_mismatch"

#: The share of items that must agree on a category other than the vendor's own before this is a
#: finding rather than a mixed basket. Two-thirds rather than a bare majority — see the module
#: docstring; the false positives are ordinary receipts.
DOMINANCE_THRESHOLD: float = 2 / 3

#: Below this many categorised items there is no "preponderance" to speak of. A two-item receipt
#: where both items disagree with the vendor is one line item away from being a coin flip.
MINIMUM_ITEMS: int = 3


def dominant_category(item_categories: tuple[str, ...]) -> tuple[str, float] | None:
    """The most common category and its share, or `None` if there is nothing to count."""
    populated = tuple(c for c in item_categories if c.strip())
    if not populated:
        return None
    category, count = Counter(populated).most_common(1)[0]
    return category, count / len(populated)


class ItemsVendorMismatchCheck:
    """§4.6, as a registry entry."""

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        if not snapshot.vendor_category:
            return inconclusive(CHECK_NAME, "vendor has no registered category to compare against")

        populated = tuple(c for c in snapshot.item_categories if c.strip())
        if len(populated) < MINIMUM_ITEMS:
            return inconclusive(
                CHECK_NAME,
                f"only {len(populated)} categorised item(s); §4.6's 'strongly suggest' needs at "
                f"least {MINIMUM_ITEMS}",
            )

        dominant = dominant_category(populated)
        if dominant is None:
            return inconclusive(CHECK_NAME, "no item categories on this receipt")

        category, share = dominant
        if category != snapshot.vendor_category and share >= DOMINANCE_THRESHOLD:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["items_vendor_mismatch"],
                Severity.LOW,
                (
                    f"{share:.0%} of items are {category!r} but the vendor is categorised "
                    f"{snapshot.vendor_category!r} — surfaced, not recategorised"
                ),
                FrozenDict(
                    {
                        "dominant_item_category": category,
                        "dominant_share": share,
                        "vendor_category": snapshot.vendor_category,
                        "item_count": len(populated),
                    }
                ),
            )

        return passed(
            CHECK_NAME,
            f"items do not strongly contradict the vendor's category (top category {category!r} "
            f"at {share:.0%})",
        )


__all__ = [
    "CHECK_NAME",
    "DOMINANCE_THRESHOLD",
    "ItemsVendorMismatchCheck",
    "MINIMUM_ITEMS",
    "dominant_category",
]

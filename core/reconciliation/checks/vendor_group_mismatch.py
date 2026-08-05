"""§4.6 — the mislabeled vendor group check.

Consumes Matching API's own candidate-scoring output. A receipt matched to a vendor whose
registered group disagrees with the group the match itself came from is a real, catchable
inconsistency — §4.6's phrasing is that this is "not a fuzzy-match confidence question alone",
which is the distinction that earns this check its own existence: a *confident* match can still
be to a vendor filed under the wrong group, and confidence says nothing about that.

Paired with `items_vendor_mismatch.py`, which asks the complementary question from the items'
side. §2 lists both, and they are genuinely two checks rather than one with a parameter: this one
compares two pieces of registry metadata about the vendor, the other compares registry metadata
against what was actually bought.

`docs/PRINCIPLES.md` §4.3 throughout: a disagreement is surfaced, never resolved. Reconciliation
does not decide whether the vendor's registered group or the match's group is the correct one —
that is Architect's data to correct, and a human's call which side is wrong.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import FLAG_TYPES, ReceiptSnapshot, Severity
from .base import flagged, inconclusive, passed

CHECK_NAME = "vendor_group_mismatch"


class VendorGroupMismatchCheck:
    """§4.6, as a registry entry.

    Reads `expected_group_for_category` from the run context: a mapping from vendor category to
    the group Architect has that category filed under. Supplied rather than held here because
    §1 puts the taxonomy in Architect and this check is a consumer of it
    (`docs/PRINCIPLES.md` §3.4) — a lookup table hardcoded in this file would be this package
    quietly defining what groups exist.
    """

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        if not snapshot.vendor_group or not snapshot.vendor_category:
            return inconclusive(
                CHECK_NAME,
                "this receipt's vendor has no registered group or no category to check it "
                "against",
            )

        expected_by_category = context.get("expected_group_for_category")
        if expected_by_category is None:
            return inconclusive(
                CHECK_NAME,
                "no category-to-group mapping supplied — Architect owns this taxonomy (§1)",
            )

        expected = expected_by_category.get(snapshot.vendor_category)
        if expected is None:
            return inconclusive(
                CHECK_NAME,
                f"category {snapshot.vendor_category!r} is not in the supplied mapping; an "
                "unregistered category is Architect's gap to close, not a mismatch",
            )

        if expected != snapshot.vendor_group:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["vendor_group_mismatch"],
                Severity.LOW,
                (
                    f"vendor is filed under group {snapshot.vendor_group!r} but its category "
                    f"{snapshot.vendor_category!r} maps to {expected!r} — surfaced, not corrected"
                ),
                FrozenDict(
                    {
                        "vendor_group": snapshot.vendor_group,
                        "vendor_category": snapshot.vendor_category,
                        "expected_group": expected,
                    }
                ),
            )

        return passed(CHECK_NAME, "vendor group agrees with its category's registered group")


__all__ = ["CHECK_NAME", "VendorGroupMismatchCheck"]

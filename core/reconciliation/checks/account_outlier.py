"""§4.4 — the account/category outlier check.

A receipt whose amount is a statistical outlier relative to *that vendor's or category's own*
historical distribution — explicitly not a fixed global threshold. §4.4 makes this "a genuine
consumer of Architect's registry rather than self-contained logic", which is why the history
arrives through a `VendorHistoryProvider` seam rather than being computed here.

**§8 resolves the statistical method: IQR, not z-score.** Its reasoning is specific and worth
keeping attached to the code — financial data is "often meaningfully skewed rather than normally
distributed (a handful of genuinely large legitimate purchases shouldn't blow out a z-score's own
assumptions the way they would for a normal distribution)". A z-score's mean and standard
deviation are both dragged by the very outliers the check is looking for, so a vendor with three
genuinely large purchases in their history develops a threshold high enough that nothing is ever
an outlier again. Quartiles do not move that way.

`docs/PRINCIPLES.md` §4.4 governs the empty case: a vendor with no history is not an outlier, it
is unknown. Flagging a first purchase would make every new vendor's first receipt a finding.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import FLAG_TYPES, ReceiptSnapshot, Severity, VendorHistoryProvider
from .base import flagged, inconclusive, passed

CHECK_NAME = "account_outlier"

#: The Tukey fence multiplier. 1.5×IQR is the standard "outlier" fence; §8 explicitly leaves the
#: specific multiplier open to "real calibration against actual data" later, so it is a named
#: constant rather than a literal buried in the arithmetic.
IQR_MULTIPLIER: float = 1.5

#: Below this many historical amounts, quartiles are not meaningful — with three points the
#: first and third quartile are adjacent and the fence is arbitrarily tight. §8's method needs a
#: distribution to describe, and four points is the minimum that has one.
MINIMUM_HISTORY: int = 4


def quartiles(values: tuple[int, ...]) -> tuple[float, float]:
    """`(Q1, Q3)` by linear interpolation over the sorted values.

    Written here rather than pulled from `statistics.quantiles` for one honest reason: that
    function's default method differs across the interpolation conventions, and a fence whose
    position depends on which convention the standard library happened to pick is a fence that
    can move under an interpreter upgrade (`docs/PRINCIPLES.md` §3.3). This is the inclusive
    convention, stated explicitly.
    """
    ordered = sorted(values)
    n = len(ordered)

    def _at(fraction: float) -> float:
        position = fraction * (n - 1)
        lower = int(position)
        upper = min(lower + 1, n - 1)
        weight = position - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight

    return _at(0.25), _at(0.75)


class AccountOutlierCheck:
    """§4.4, as a registry entry. Reads `vendor_history` from the run context."""

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        amount = snapshot.total_centavos
        if amount is None:
            return inconclusive(CHECK_NAME, "no total on this receipt to compare")

        provider = context.get("vendor_history")
        if not isinstance(provider, VendorHistoryProvider):
            return inconclusive(
                CHECK_NAME,
                "no vendor-history provider supplied — §4.4 needs Architect's learned history",
            )

        history = await provider.historical_amounts(
            snapshot.vendor_name, snapshot.vendor_category
        )
        if len(history) < MINIMUM_HISTORY:
            return inconclusive(
                CHECK_NAME,
                f"only {len(history)} historical amounts for this vendor/category; "
                f"a distribution needs at least {MINIMUM_HISTORY}",
            )

        q1, q3 = quartiles(history)
        iqr = q3 - q1
        lower_fence = q1 - IQR_MULTIPLIER * iqr
        upper_fence = q3 + IQR_MULTIPLIER * iqr

        if amount < lower_fence or amount > upper_fence:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["account_outlier"],
                Severity.LOW,
                (
                    f"{amount} centavos falls outside this vendor's own IQR fence "
                    f"[{lower_fence:.0f}, {upper_fence:.0f}] over {len(history)} prior receipts"
                ),
                FrozenDict(
                    {
                        "amount_centavos": amount,
                        "q1": q1,
                        "q3": q3,
                        "lower_fence": lower_fence,
                        "upper_fence": upper_fence,
                        "history_size": len(history),
                    }
                ),
            )

        return passed(CHECK_NAME, "amount is within this vendor's own historical range")


__all__ = [
    "CHECK_NAME",
    "IQR_MULTIPLIER",
    "MINIMUM_HISTORY",
    "AccountOutlierCheck",
    "quartiles",
]

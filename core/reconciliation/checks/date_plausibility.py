"""§4.3 — the date plausibility check.

A receipt dated in the future, or implausibly far in the past relative to when it was actually
scanned, is very likely an OCR misread — a `7` read as a `1`, a two-digit year misparsed —
rather than a real anomaly.

**The bounds are deliberately generous, and §4.3 says why**: "not a strict same-day requirement
that would false-positive on legitimate batch-processing of older receipts." Someone digitising
three years of shoeboxed receipts is the *normal* use of this system, not an edge case, and a
tight bound would flag their entire archive. The future bound is tight and the past bound is
loose because the two errors are not symmetric: a receipt cannot legitimately be dated tomorrow,
but it can legitimately be five years old and only now scanned.

Measured against `uploaded_at` rather than against now, so a sweep run today over receipts
uploaded three years ago judges them by when they were actually scanned. Judging old uploads by
today's clock would make every receipt in an archive gradually become implausible with the
passage of time alone — a check whose verdicts change without the data changing.
"""

from __future__ import annotations

from datetime import date

from common.frozen_dict import FrozenDict

from ..contracts import FLAG_TYPES, ReceiptSnapshot, Severity, utcnow
from .base import flagged, inconclusive, passed

CHECK_NAME = "date_plausibility"

#: §4.3's "more than a few days in the future". Not zero: a receipt scanned across a timezone
#: boundary, or from a till whose clock is a day out, is ordinary rather than suspicious.
FUTURE_TOLERANCE_DAYS: int = 3

#: §4.3's "more than several years old". Seven years is deliberate rather than round — it is the
#: BIR's own record-retention period, so a receipt older than this is past the window it would
#: be needed for anyway, and flagging it costs nothing a filer needed.
PAST_TOLERANCE_DAYS: int = 365 * 7


class DatePlausibilityCheck:
    """§4.3, as a registry entry."""

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        transaction_date = snapshot.transaction_date
        if transaction_date is None:
            return inconclusive(CHECK_NAME, "no transaction date extracted from this receipt")

        reference: date = (
            snapshot.uploaded_at.date() if snapshot.uploaded_at is not None else utcnow().date()
        )
        delta_days = (transaction_date - reference).days

        if delta_days > FUTURE_TOLERANCE_DAYS:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["date_plausibility"],
                Severity.MEDIUM,
                (
                    f"transaction date {transaction_date.isoformat()} is {delta_days} days "
                    f"after upload ({reference.isoformat()}) — likely an OCR misread"
                ),
                FrozenDict({"delta_days": delta_days, "direction": "future"}),
            )

        if -delta_days > PAST_TOLERANCE_DAYS:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["date_plausibility"],
                Severity.LOW,
                (
                    f"transaction date {transaction_date.isoformat()} is {-delta_days} days "
                    f"before upload ({reference.isoformat()}) — beyond the BIR retention window"
                ),
                FrozenDict({"delta_days": delta_days, "direction": "past"}),
            )

        return passed(CHECK_NAME, f"transaction date is {delta_days} days from upload")


__all__ = [
    "CHECK_NAME",
    "DatePlausibilityCheck",
    "FUTURE_TOLERANCE_DAYS",
    "PAST_TOLERANCE_DAYS",
]

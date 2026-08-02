"""§4.12 — the ATP (Authority to Print) validity check, the twelfth and final check.

A real BIR audit red flag, raised fresh in V3 rather than inherited from V2: an expired Authority
to Print on a vendor's receipt is exactly the kind of thing a BIR audit looks for. Most
BIR-compliant receipts print the ATP number and its validity period near the vendor's TIN — a
field OCR already extracts alongside vendor, date and amount when present, so this check needs no
new extraction capability of its own.

**The three-state result is the point of this check, not an implementation detail.** §4.12 is
unusually explicit: a mismatch is "surfaced via Review/Flagging, never auto-rejected, since a
printed date being illegible or an ATP field OCR failed to capture at all is a genuinely
different, softer case than a confirmed date-outside-window mismatch, and **conflating the two
would misrepresent the actual finding**."

So a receipt with no ATP window is `INCONCLUSIVE`, never `FLAGGED`. Flagging it would tell a
filer their vendor's authority had expired when what actually happened is that a scan was
blurry — a false accusation about a third party, generated automatically, at scale.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import FLAG_TYPES, ReceiptSnapshot, Severity
from .base import flagged, inconclusive, passed

CHECK_NAME = "atp_validity"


class AtpValidityCheck:
    """§4.12, as a registry entry."""

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        transaction_date = snapshot.transaction_date
        valid_from = snapshot.atp_valid_from
        valid_until = snapshot.atp_valid_until

        if transaction_date is None:
            return inconclusive(
                CHECK_NAME, "no transaction date to compare against the ATP window"
            )

        if valid_from is None and valid_until is None:
            return inconclusive(
                CHECK_NAME,
                "no ATP validity window on this receipt — absent or illegible, which §4.12 "
                "keeps distinct from a confirmed mismatch",
            )

        if valid_from is not None and transaction_date < valid_from:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["atp_validity"],
                Severity.HIGH,
                (
                    f"transaction dated {transaction_date.isoformat()} predates the ATP "
                    f"validity window opening {valid_from.isoformat()}"
                ),
                FrozenDict(
                    {
                        "transaction_date": transaction_date.isoformat(),
                        "atp_valid_from": valid_from.isoformat(),
                        "direction": "before_window",
                    }
                ),
            )

        if valid_until is not None and transaction_date > valid_until:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["atp_validity"],
                Severity.HIGH,
                (
                    f"transaction dated {transaction_date.isoformat()} falls after the ATP "
                    f"expired on {valid_until.isoformat()}"
                ),
                FrozenDict(
                    {
                        "transaction_date": transaction_date.isoformat(),
                        "atp_valid_until": valid_until.isoformat(),
                        "direction": "after_window",
                    }
                ),
            )

        return passed(CHECK_NAME, "transaction date falls inside the printed ATP window")


__all__ = ["CHECK_NAME", "AtpValidityCheck"]

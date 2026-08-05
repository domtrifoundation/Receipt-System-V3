"""§4.11 — the address/vendor geo cross-check, applied backward to old receipts.

§4.11 records how this check was found: "a real, previously-missing check, found while tracing
Geo/Address API's own two legitimate callers (`docs/PRINCIPLES.md` §1.9)" — this API was supposed
to be able to call Geo/Address's reverse-geocoding capability against already-written receipts,
and no check in the inventory actually did until that trace.

**This is the canonical §1.9 case in this package.** §4.11's sketch is unambiguous: it "calls the
identical underlying Geo/Address function Execution Core's own GEOD stage calls for new receipts
— not a separate 'old receipt' implementation." That function is
`core.geo_address.reverse_check.reverse_check`, and it arrives here by injection rather than by
import so this package stays importable where Geo/Address is not installed
(`docs/PRINCIPLES.md` §1.3). The identity of the injected callable — that it *is* that function
object and not a lookalike — is what this package's §1.9 test pins; a test asserting only that
both paths "agree" would pass right up until the day they quietly stopped.

**Budget-gated, not run unconditionally.** §5 singles this check out: it is "a genuine network
call... budget-gated by the same caller-policy discipline Geo/Address's own deep-dive states
rather than run unconditionally against every receipt in a sweep". Firing a geocode for every
receipt in a ten-thousand-row retroactive sweep is a real bill and a real rate-limit breach. The
gate is the caller's to open, so this check is `INCONCLUSIVE` — not `PASSED` — when no geo
context was supplied.

**A discrepancy is surfaced, never auto-corrected** (§4.11, `docs/PRINCIPLES.md` §4.3). A
mismatch between the OCR-read vendor name and what is actually at the geocoded address is a
corroboration signal; it does not establish which side is wrong.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import FLAG_TYPES, ReceiptSnapshot, Severity
from .base import flagged, inconclusive, passed

CHECK_NAME = "geo_vendor_cross_reference"


class GeoVendorCrossReferenceCheck:
    """§4.11, as a registry entry.

    Reads three things from the run context, all supplied by the caller that opened the budget
    gate: `geo_reverse_check` (the identical function Execution Core's `GEOD` stage calls),
    `geo_address` (the resolved address for this receipt), and `geo_providers`.
    """

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        reverse_check = context.get("geo_reverse_check")
        if reverse_check is None:
            return inconclusive(
                CHECK_NAME,
                "no geo reverse-check supplied — §5 budget-gates this check rather than firing "
                "a network call for every receipt in a sweep",
            )

        if not snapshot.vendor_name.strip():
            return inconclusive(
                CHECK_NAME, "no OCR-read vendor name to cross-reference against the address"
            )

        address = context.get("geo_address")
        if address is None:
            return inconclusive(
                CHECK_NAME,
                "this receipt has no resolved address — the original run either skipped the "
                "lookup for budget reasons or it failed at the time (§4.11)",
            )

        providers = context.get("geo_providers") or ()

        try:
            vendor_at_address, discrepancy, provider_results = await reverse_check(
                address, snapshot.vendor_name, tuple(providers)
            )
        except Exception as exc:  # noqa: BLE001 - errors are data (§4.1)
            return inconclusive(
                CHECK_NAME,
                f"reverse lookup failed ({type(exc).__name__}: {exc}); an unreachable geo "
                "provider is not evidence of a discrepancy",
            )

        if not vendor_at_address:
            return inconclusive(
                CHECK_NAME,
                "reverse lookup returned no business at this address — nothing to compare, "
                "which Geo/Address itself treats as a skip rather than a failure",
            )

        if discrepancy:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["geo_vendor_cross_reference"],
                Severity.MEDIUM,
                (
                    f"receipt reads vendor {snapshot.vendor_name!r} but the geocoded address "
                    f"reports {vendor_at_address!r} — surfaced, not auto-corrected"
                ),
                FrozenDict(
                    {
                        "vendor_on_receipt": snapshot.vendor_name,
                        "vendor_at_address": vendor_at_address,
                        "provider_count": len(provider_results),
                    }
                ),
            )

        return passed(
            CHECK_NAME, f"vendor name corroborated against the address ({vendor_at_address!r})"
        )


__all__ = ["CHECK_NAME", "GeoVendorCrossReferenceCheck"]

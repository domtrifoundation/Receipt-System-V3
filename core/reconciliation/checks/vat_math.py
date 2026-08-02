"""§4.1 — the VAT math check.

Philippine VAT is a fixed, computable relationship between the VAT-exclusive amount, the VAT
amount and the VAT-inclusive total: 12% standard rate. A receipt whose printed subtotal, VAT and
total do not reconcile to within a small rounding tolerance is a real, mechanical finding rather
than a fuzzy one — which is what makes this check worth having at all.

**Two deliberate divergences from §4.1's sketch, both of which change results rather than style.**

1. **Integer centavos, not floats.** That sketch reads
   `check_vat_math(subtotal: float, vat: float, total: float, tolerance: float = 0.02)`. Worth
   being accurate about the stake rather than overstating it: at the magnitudes a Philippine
   receipt actually occupies, the two-centavo tolerance is wide enough to absorb float drift, so
   the sketch is not producing wrong answers today — a test verifies that agreement rather than
   asserting a bug that is not there. What integer arithmetic buys is that the guarantee does
   not *depend* on the tolerance being generous. Someone tightening it to zero centavos later
   would silently turn an absorbed rounding artefact into a stream of false findings, and money
   in binary floating point is the repo-wide rule anyway (`core/billing/` reached it first).
2. **A zero-rated or VAT-exempt receipt is not a hit.** §4.1's sketch computes 12% of the
   subtotal unconditionally, which would flag every export sale, every senior-citizen and PWD
   discounted purchase, and every VAT-exempt vendor's receipt in the country — an enormous
   false-positive class in a Philippine system specifically. Those treatments are checked for
   the relationship they actually have (no VAT, total equals subtotal), and an unrecognised
   treatment is `INCONCLUSIVE` rather than assumed vatable.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import (
    FLAG_TYPES,
    KNOWN_VAT_TREATMENTS,
    ReceiptSnapshot,
    Severity,
    VAT_RATE_PERCENT,
    VAT_TOLERANCE_CENTAVOS,
    VATABLE,
)
from .base import flagged, inconclusive, passed

CHECK_NAME = "vat_math"


def expected_vat_centavos(subtotal_centavos: int) -> int:
    """12% of the subtotal, rounded half-up to the centavo, in exact integer arithmetic.

    `(x * 12 + 50) // 100` is round-half-up for non-negative values — the convention Philippine
    receipts are printed with, and distinct from Python's built-in `round`, which resolves exact
    halves to even.

    At 12% the two modes provably cannot disagree: `12c ≡ 50 (mod 100)` reduces to
    `6c ≡ 25 (mod 50)`, even on the left and odd on the right, so no centavo amount lands on an
    exact half. That is a fact about the number 12 rather than about this function, which is
    why a test pins it — a future rate change to 10% or 15% would quietly make the rounding mode
    load-bearing, and the question should surface then rather than be discovered in a filing.
    """
    if subtotal_centavos < 0:
        return -((-subtotal_centavos * VAT_RATE_PERCENT + 50) // 100)
    return (subtotal_centavos * VAT_RATE_PERCENT + 50) // 100


class VatMathCheck:
    """§4.1, as a registry entry."""

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        subtotal = snapshot.subtotal_centavos
        vat = snapshot.vat_centavos
        total = snapshot.total_centavos

        if subtotal is None or vat is None or total is None:
            return inconclusive(
                CHECK_NAME,
                "one or more of subtotal/VAT/total is absent — nothing to reconcile",
            )

        treatment = snapshot.vat_treatment
        if treatment not in KNOWN_VAT_TREATMENTS:
            return inconclusive(
                CHECK_NAME,
                f"unrecognised VAT treatment {treatment!r}; not assuming it is vatable",
            )

        if treatment != VATABLE:
            if vat != 0:
                return flagged(
                    CHECK_NAME,
                    FLAG_TYPES["vat_math"],
                    Severity.MEDIUM,
                    f"{treatment} receipt carries a non-zero VAT amount of {vat} centavos",
                    FrozenDict({"treatment": treatment, "vat_centavos": vat}),
                )
            if abs(total - subtotal) > VAT_TOLERANCE_CENTAVOS:
                return flagged(
                    CHECK_NAME,
                    FLAG_TYPES["vat_math"],
                    Severity.MEDIUM,
                    f"{treatment} receipt total {total} does not equal subtotal {subtotal}",
                    FrozenDict({"treatment": treatment, "subtotal": subtotal, "total": total}),
                )
            return passed(CHECK_NAME, f"{treatment}: no VAT expected and none charged")

        expected_vat = expected_vat_centavos(subtotal)
        expected_total = subtotal + expected_vat
        vat_off_by = abs(vat - expected_vat)
        total_off_by = abs(total - expected_total)

        if vat_off_by > VAT_TOLERANCE_CENTAVOS or total_off_by > VAT_TOLERANCE_CENTAVOS:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["vat_math"],
                Severity.MEDIUM,
                (
                    f"expected VAT {expected_vat} and total {expected_total} centavos, "
                    f"receipt printed {vat} and {total}"
                ),
                FrozenDict(
                    {
                        "expected_vat_centavos": expected_vat,
                        "expected_total_centavos": expected_total,
                        "vat_off_by_centavos": vat_off_by,
                        "total_off_by_centavos": total_off_by,
                    }
                ),
            )

        return passed(CHECK_NAME, "subtotal, VAT and total reconcile within tolerance")


__all__ = ["CHECK_NAME", "VatMathCheck", "expected_vat_centavos"]

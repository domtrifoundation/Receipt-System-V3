"""The Philippine-BIR-specific checks: VAT math, TIN format, BIR completeness, ATP (§4.1, §4.2, §4.7, §4.12).

§7 asks for "each check in §4 gets its own labeled test fixture set (a known-bad VAT math
receipt, a malformed TIN, an implausible date)". These are those fixture sets, written against
the arithmetic and the edge cases that actually occur on Philippine receipts rather than against
a happy path — a VAT checker that only handles the clean case is a VAT checker that flags every
zero-rated export sale in the country.

Every fixture here is invented. See `_doubles.py`.
"""

from __future__ import annotations

from datetime import date

import pytest

from common.frozen_dict import FrozenDict
from core.reconciliation.checks.atp_validity import AtpValidityCheck
from core.reconciliation.checks.bir_completeness import (
    BirCompletenessCheck,
    REQUIRED_FIELDS,
    missing_fields,
)
from core.reconciliation.checks.tin_format import (
    TinFormatCheck,
    is_structurally_valid,
    normalize_tin,
)
from core.reconciliation.checks.vat_math import VatMathCheck, expected_vat_centavos
from core.reconciliation.contracts import (
    CheckOutcome,
    FLAG_TYPES,
    Severity,
    VAT_EXEMPT,
    ZERO_RATED,
)

from ._doubles import FAKE_TIN, run, snapshot

EMPTY = FrozenDict({})


# ---------------------------------------------------------------------------------------------
# §4.1 — VAT math
# ---------------------------------------------------------------------------------------------


def test_a_receipt_whose_vat_and_total_reconcile_is_not_flagged():
    """The ordinary case: ₱1,000.00 subtotal, ₱120.00 VAT, ₱1,120.00 total."""
    result = run(VatMathCheck().run(snapshot(), EMPTY))
    assert result.outcome is CheckOutcome.PASSED


def test_a_receipt_whose_printed_vat_does_not_reconcile_is_flagged_at_medium():
    """§4.1 names `medium` severity directly, and a mismatch is the finding this check exists for.

    ₱1,000.00 subtotal with ₱100.00 of VAT printed is off by ₱20.00 — a real error rather than a
    rounding artefact, and exactly the kind of thing a BIR filing needs caught before submission.
    """
    result = run(
        VatMathCheck().run(snapshot(vat_centavos=10_000, total_centavos=110_000), EMPTY)
    )
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.flag_type == FLAG_TYPES["vat_math"]
    assert result.severity is Severity.MEDIUM


def test_a_two_centavo_rounding_difference_is_within_tolerance_and_not_flagged():
    """§4.1's tolerance exists because tills round, and it must actually be honoured.

    Without it every receipt whose printed VAT landed a centavo either side of the exact figure
    would be a finding — which is most of them, and the check would be discarded as noise.
    """
    result = run(
        VatMathCheck().run(snapshot(vat_centavos=12_002, total_centavos=112_002), EMPTY)
    )
    assert result.outcome is CheckOutcome.PASSED


def test_a_three_centavo_difference_is_outside_tolerance_and_is_flagged():
    """The other side of the same boundary. A tolerance that never rejects anything is not a
    tolerance, and a test that only proves the accepting side would pass against one."""
    result = run(
        VatMathCheck().run(snapshot(vat_centavos=12_003, total_centavos=112_003), EMPTY)
    )
    assert result.outcome is CheckOutcome.FLAGGED


def test_a_zero_rated_receipt_with_no_vat_is_not_a_math_error():
    """§4.1's sketch computes 12% unconditionally, which would flag every export sale in the country.

    A zero-rated receipt legitimately carries no VAT and a total equal to its subtotal. Treating
    that as a mismatch would generate an enormous false-positive class in a Philippine system
    specifically — and it is the class most likely to belong to a business filing exports.
    """
    result = run(
        VatMathCheck().run(
            snapshot(vat_treatment=ZERO_RATED, vat_centavos=0, total_centavos=100_000), EMPTY
        )
    )
    assert result.outcome is CheckOutcome.PASSED


def test_a_vat_exempt_receipt_with_no_vat_is_not_a_math_error():
    """The senior-citizen and PWD discount case, which is ordinary rather than exceptional here."""
    result = run(
        VatMathCheck().run(
            snapshot(vat_treatment=VAT_EXEMPT, vat_centavos=0, total_centavos=100_000), EMPTY
        )
    )
    assert result.outcome is CheckOutcome.PASSED


def test_a_zero_rated_receipt_that_nonetheless_charged_vat_is_flagged():
    """The genuine error inside the exemption, which a blanket "skip exempt receipts" would miss.

    A receipt claiming zero-rated treatment while charging 12% is either miscategorised or
    overcharging the customer, and both are worth a human's attention.
    """
    result = run(
        VatMathCheck().run(
            snapshot(vat_treatment=ZERO_RATED, vat_centavos=12_000, total_centavos=112_000),
            EMPTY,
        )
    )
    assert result.outcome is CheckOutcome.FLAGGED


def test_an_unrecognised_vat_treatment_is_inconclusive_rather_than_assumed_vatable():
    """`docs/PRINCIPLES.md` §4.4, and §4.12's insistence that "could not check" stays distinct.

    Assuming an unknown treatment is vatable would apply a 12% test to receipts under a rule this
    code has never heard of, producing confident findings about arithmetic it has no basis to
    judge.
    """
    result = run(VatMathCheck().run(snapshot(vat_treatment="excise_special"), EMPTY))
    assert result.outcome is CheckOutcome.INCONCLUSIVE


def test_a_receipt_missing_its_amounts_is_inconclusive_not_passed():
    """Absent fields are BIR completeness's finding, and passing them here would certify a
    receipt as arithmetically sound when no arithmetic was performed."""
    result = run(VatMathCheck().run(snapshot(subtotal_centavos=None), EMPTY))
    assert result.outcome is CheckOutcome.INCONCLUSIVE


@pytest.mark.parametrize(
    "subtotal, expected",
    [
        (100_000, 12_000),
        (1, 0),
        (4, 0),
        (5, 1),
        (12_549, 1_506),
        (99_999_999, 12_000_000),
    ],
)
def test_vat_is_computed_in_exact_integer_arithmetic_and_rounds_half_up(subtotal, expected):
    """§4.1's sketch uses floats, and `0.12` is not representable in binary floating point.

    The error accumulates with the amount: on a large receipt it approaches the two-centavo
    tolerance the check is measuring against, at which point the checker starts flagging correct
    receipts and passing incorrect ones. Half-up rather than Python's banker's rounding, because
    that is the convention the printed receipt used.
    """
    assert expected_vat_centavos(subtotal) == expected


def test_a_twelve_percent_rate_on_whole_centavos_never_lands_on_an_exact_half():
    """Why the rounding *mode* is provably irrelevant at 12%, and why that stops being true if
    the rate ever changes.

    `12c ≡ 50 (mod 100)` reduces to `6c ≡ 25 (mod 50)`, whose left side is always even and whose
    right side is odd — so there is no centavo amount at which half-up and half-even could
    disagree. That is a fact about the number 12, not about this implementation, and it is
    exactly the kind of quiet assumption a rate change would invalidate without any test
    noticing. Pinned here so a future 10% or 15% VAT surfaces the question rather than silently
    making the rounding mode load-bearing.
    """
    assert not [c for c in range(1, 100_000) if (c * 12) % 100 == 50]


def test_integer_arithmetic_is_exact_by_construction_rather_than_by_the_tolerance_absorbing_it():
    """The honest reason for diverging from §4.1's float sketch, stated as a test.

    At realistic receipt magnitudes the float formulation and this one agree — the two-centavo
    tolerance is wide enough to absorb float drift, so this is not a live bug being fixed. What
    integer arithmetic buys is that the guarantee does not *depend* on that: someone tightening
    the tolerance to zero centavos later would not silently turn an absorbed rounding artefact
    into a stream of false findings. Verified against the float path across the range a
    Philippine receipt actually occupies, up to ₱30,000.
    """
    disagreements = [
        c
        for c in range(1, 3_000_000, 7)
        if expected_vat_centavos(c) != round(round(c / 100 * 0.12, 2) * 100)
    ]
    assert disagreements == []
    assert expected_vat_centavos(0) == 0


# ---------------------------------------------------------------------------------------------
# §4.2 — TIN format
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "123-456-789",
        "123-456-789-000",
        "123456789",
        "123456789000",
        "123 456 789 000",
        "123-456-789-00000",
    ],
)
def test_real_bir_tin_shapes_are_accepted(raw):
    """Nine base digits, optionally a 3- or 5-digit branch code, in any separator style.

    The 5-digit branch code appears on older receipts; rejecting it would flag an entire archive
    of pre-2010 receipts as malformed, which is precisely the false-positive class a retroactive
    sweep must not produce.
    """
    assert is_structurally_valid(raw) is True


@pytest.mark.parametrize(
    "raw",
    ["12345678", "1234567890", "123-456-78O", "abc-def-ghi", "123-456-789-0", "1234567890000000"],
)
def test_malformed_tins_are_rejected(raw):
    """The OCR misreads this check exists to catch — a dropped digit, an `O` read for a `0`."""
    assert is_structurally_valid(raw) is False


def test_separators_are_stripped_before_matching_because_ocr_renders_them_inconsistently():
    """A receipt is not malformed because its dash scanned as an en-dash.

    Making the separator part of the pattern would turn a rendering artefact into a finding
    about the vendor's TIN.
    """
    assert normalize_tin("123‐456—789") == "123456789"
    assert is_structurally_valid("123‐456—789") is True


def test_a_malformed_tin_is_flagged_with_the_digit_count_as_evidence():
    """A flag saying only "invalid" sends a human to re-read the receipt with no idea what to
    look for. The digit count says immediately whether OCR dropped a digit or read garbage."""
    result = run(TinFormatCheck().run(snapshot(vendor_tin="12345678"), EMPTY))
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.flag_type == FLAG_TYPES["tin_format"]
    assert result.evidence["digits"] == 8


def test_an_absent_tin_is_inconclusive_here_and_left_to_bir_completeness():
    """Two checks reporting the same problem would put two flags in a queue for one defect.

    §4.7 owns presence; this check owns shape. A missing TIN has no shape to be wrong about.
    """
    result = run(TinFormatCheck().run(snapshot(vendor_tin=""), EMPTY))
    assert result.outcome is CheckOutcome.INCONCLUSIVE


def test_a_passing_tin_check_never_claims_the_tin_actually_exists():
    """§4.2 is explicit that this is structural, "not a validity check against BIR's own records".

    The distinction matters legally as much as technically: a system reporting a TIN as valid
    implies an authority it does not have, and this check cannot detect a
    fraudulent-but-well-formatted TIN at all.
    """
    result = run(TinFormatCheck().run(snapshot(vendor_tin=FAKE_TIN), EMPTY))
    assert result.outcome is CheckOutcome.PASSED
    assert "existence not checked" in result.detail


# ---------------------------------------------------------------------------------------------
# §4.7 — BIR completeness
# ---------------------------------------------------------------------------------------------


def test_a_complete_receipt_passes_the_completeness_check():
    assert run(BirCompletenessCheck().run(snapshot(), EMPTY)).outcome is CheckOutcome.PASSED


@pytest.mark.parametrize("field_name", sorted(REQUIRED_FIELDS))
def test_every_bir_required_field_is_actually_checked_for(field_name):
    """A required field that lives in a table nothing reads is not a requirement.

    Parametrised over the real table so adding an entry without wiring it up fails here rather
    than silently going unchecked on every receipt.
    """
    absent = "" if isinstance(getattr(snapshot(), field_name), str) else None
    result = run(BirCompletenessCheck().run(snapshot(**{field_name: absent}), EMPTY))
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.flag_type == FLAG_TYPES["bir_completeness"]


def test_a_zero_vat_amount_counts_as_present_rather_than_missing():
    """The single most likely bug in a presence check, and it would misreport a whole class of
    lawful receipts.

    A zero-rated receipt's VAT amount is legitimately `0`. A falsiness test would report every
    one of them as missing BIR-required documentation.
    """
    assert missing_fields(snapshot(vat_centavos=0, vat_treatment=ZERO_RATED)) == ()


def test_completeness_is_reported_as_high_severity_and_lists_every_missing_field():
    """A filer needs one trip back to the receipt, not one per missing field."""
    result = run(
        BirCompletenessCheck().run(snapshot(vendor_tin="", receipt_number=""), EMPTY)
    )
    assert result.severity is Severity.HIGH
    assert len(result.evidence["missing"]) == 2


def test_completeness_is_a_presence_check_and_not_a_correctness_check():
    """§4.7: "distinct from VAT math's *correctness* check".

    A receipt with every field present but arithmetic that does not reconcile is complete
    documentation with an error in it — a different finding with a different remedy, which is
    why folding the two together would report one problem where there are two.
    """
    arithmetically_wrong = snapshot(vat_centavos=99_999, total_centavos=199_999)
    assert (
        run(BirCompletenessCheck().run(arithmetically_wrong, EMPTY)).outcome
        is CheckOutcome.PASSED
    )
    assert run(VatMathCheck().run(arithmetically_wrong, EMPTY)).outcome is CheckOutcome.FLAGGED


# ---------------------------------------------------------------------------------------------
# §4.12 — ATP validity
# ---------------------------------------------------------------------------------------------


def test_a_transaction_inside_the_printed_atp_window_passes():
    assert run(AtpValidityCheck().run(snapshot(), EMPTY)).outcome is CheckOutcome.PASSED


def test_a_transaction_after_the_atp_expired_is_flagged_at_high_severity():
    """§4.12: an expired Authority to Print is "a real BIR audit red flag".

    High severity because this is the kind of finding that surfaces during an actual audit, when
    it is far more expensive to discover than it is now.
    """
    result = run(
        AtpValidityCheck().run(snapshot(atp_valid_until=date(2025, 1, 1)), EMPTY)
    )
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.severity is Severity.HIGH
    assert result.evidence["direction"] == "after_window"


def test_a_transaction_predating_the_atp_window_is_also_flagged():
    """A receipt dated before its own ATP was issued is as much an inconsistency as one dated
    after it expired, and a check that only looked forward would miss half of them."""
    result = run(AtpValidityCheck().run(snapshot(atp_valid_from=date(2027, 1, 1)), EMPTY))
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.evidence["direction"] == "before_window"


def test_a_transaction_on_the_expiry_date_itself_is_inside_the_window():
    """An ATP is valid through its printed end date, not up to the day before.

    Off by one here accuses a vendor of an expired authority on a day it was genuinely valid.
    """
    result = run(
        AtpValidityCheck().run(
            snapshot(transaction_date=date(2029, 1, 1), atp_valid_until=date(2029, 1, 1)), EMPTY
        )
    )
    assert result.outcome is CheckOutcome.PASSED


def test_a_missing_atp_window_is_inconclusive_and_never_flagged():
    """§4.12's own words: an illegible or uncaptured ATP field "is a genuinely different, softer
    case than a confirmed date-outside-window mismatch, and conflating the two would misrepresent
    the actual finding."

    Flagging it would tell a filer their vendor's authority had expired when what actually
    happened is that a scan was blurry — an automatically generated false accusation about a
    third party, at scale.
    """
    result = run(
        AtpValidityCheck().run(snapshot(atp_valid_from=None, atp_valid_until=None), EMPTY)
    )
    assert result.outcome is CheckOutcome.INCONCLUSIVE
    assert result.flag_type == ""


def test_a_one_sided_atp_window_is_still_checked_on_the_side_it_has():
    """Half the information is not none of it.

    A receipt printing only an expiry date can still be shown to fall after it, and discarding
    that as inconclusive would waste a genuine finding.
    """
    result = run(
        AtpValidityCheck().run(
            snapshot(atp_valid_from=None, atp_valid_until=date(2025, 6, 1)), EMPTY
        )
    )
    assert result.outcome is CheckOutcome.FLAGGED

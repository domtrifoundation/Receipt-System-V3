"""The remaining check inventory: date plausibility, outliers, duplicates, mismatches, archives.

§4.3, §4.4, §4.5, §4.6, §4.10 — §7 asks for a labeled fixture set per check, and the fixtures
here are chosen to be the cases that actually occur rather than the ones that are easy to write.
Several tests exist specifically to pin a *non*-finding: a batch-scanned three-year-old receipt,
a mixed supermarket basket, two genuine same-day purchases at the same price. Those are the
false positives that would make a check get switched off, which is worse than not having it.

Every fixture is invented. See `_doubles.py`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from common.frozen_dict import FrozenDict
from core.reconciliation.checks.account_outlier import AccountOutlierCheck, quartiles
from core.reconciliation.checks.date_plausibility import DatePlausibilityCheck
from core.reconciliation.checks.items_vendor_mismatch import ItemsVendorMismatchCheck
from core.reconciliation.checks.orphaned_archive_reference import (
    OrphanedArchiveReferenceCheck,
)
from core.reconciliation.checks.semantic_duplicate import (
    SemanticDuplicateCheck,
    amounts_match,
    looks_like_same_transaction,
)
from core.reconciliation.checks.vendor_group_mismatch import VendorGroupMismatchCheck
from core.reconciliation.contracts import CheckOutcome, FLAG_TYPES, Severity

from ._doubles import (
    FakeBlobLocations,
    FakeCandidateSource,
    FakeVendorHistory,
    run,
    snapshot,
)

EMPTY = FrozenDict({})


# ---------------------------------------------------------------------------------------------
# §4.3 — date plausibility
# ---------------------------------------------------------------------------------------------


def test_a_receipt_dated_the_day_before_upload_is_plausible():
    assert run(DatePlausibilityCheck().run(snapshot(), EMPTY)).outcome is CheckOutcome.PASSED


def test_a_receipt_dated_well_into_the_future_is_flagged_as_a_likely_ocr_misread():
    """§4.3's stated cause: "a `7` read as a `1`, a two-digit year misparsed".

    A receipt cannot legitimately be dated next year, so this direction is safe to bound tightly.
    """
    result = run(
        DatePlausibilityCheck().run(snapshot(transaction_date=date(2027, 3, 14)), EMPTY)
    )
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.evidence["direction"] == "future"


def test_a_receipt_dated_a_day_or_two_ahead_of_upload_is_not_flagged():
    """A till whose clock is a day out, or a scan across a timezone boundary, is ordinary.

    §4.3 asks for "a generous but real bound", and a zero-tolerance future check would flag
    routine clock skew as a data-integrity finding.
    """
    result = run(
        DatePlausibilityCheck().run(
            snapshot(transaction_date=date(2026, 3, 16)), EMPTY
        )
    )
    assert result.outcome is CheckOutcome.PASSED


def test_a_three_year_old_receipt_scanned_today_is_not_flagged():
    """§4.3 is explicit that a strict bound "would false-positive on legitimate batch-processing
    of older receipts".

    Someone digitising three years of shoeboxed receipts is the *normal* use of this system. A
    check that flagged their whole archive on upload would be indistinguishable from the system
    being broken.
    """
    result = run(
        DatePlausibilityCheck().run(snapshot(transaction_date=date(2023, 4, 2)), EMPTY)
    )
    assert result.outcome is CheckOutcome.PASSED


def test_a_receipt_older_than_the_bir_retention_window_is_flagged_at_low_severity():
    """Low rather than medium: an eight-year-old receipt is probably a misparsed year, but it
    might genuinely be an eight-year-old receipt, and nothing is at stake in either case."""
    result = run(
        DatePlausibilityCheck().run(snapshot(transaction_date=date(2015, 1, 1)), EMPTY)
    )
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.severity is Severity.LOW


def test_plausibility_is_measured_against_upload_time_and_not_against_today():
    """A check whose verdicts change without the data changing is not a check.

    Judging old uploads by today's clock would make every receipt in an archive gradually become
    implausible through the passage of time alone — a sweep run in 2030 would flag everything a
    sweep run in 2026 passed, with no receipt having changed.
    """
    long_ago = datetime(2019, 1, 10, tzinfo=timezone.utc)
    result = run(
        DatePlausibilityCheck().run(
            snapshot(transaction_date=date(2019, 1, 9), uploaded_at=long_ago), EMPTY
        )
    )
    assert result.outcome is CheckOutcome.PASSED


def test_a_receipt_with_no_transaction_date_is_inconclusive():
    result = run(DatePlausibilityCheck().run(snapshot(transaction_date=None), EMPTY))
    assert result.outcome is CheckOutcome.INCONCLUSIVE


# ---------------------------------------------------------------------------------------------
# §4.4 — account/category outlier
# ---------------------------------------------------------------------------------------------


def test_an_amount_far_outside_the_vendors_own_history_is_flagged():
    """§4.4: relative to "that vendor's/category's own historical distribution", not a global bar.

    ₱5,000 at a sari-sari store whose receipts are all around ₱100 is a real anomaly; the same
    ₱5,000 at a hardware supplier is unremarkable. A fixed global threshold cannot express that.
    """
    history = FakeVendorHistory((9_000, 10_000, 11_000, 12_000, 10_500))
    result = run(
        AccountOutlierCheck().run(
            snapshot(total_centavos=500_000), FrozenDict({"vendor_history": history})
        )
    )
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.flag_type == FLAG_TYPES["account_outlier"]


def test_an_ordinary_amount_within_the_vendors_range_is_not_flagged():
    history = FakeVendorHistory((9_000, 10_000, 11_000, 12_000, 10_500))
    result = run(
        AccountOutlierCheck().run(
            snapshot(total_centavos=10_200), FrozenDict({"vendor_history": history})
        )
    )
    assert result.outcome is CheckOutcome.PASSED


def test_a_vendor_with_too_little_history_is_inconclusive_rather_than_an_outlier():
    """`docs/PRINCIPLES.md` §4.4: unknown is not the same as anomalous.

    Flagging against a two-point history would make every new vendor's first few receipts a
    finding — the review queue would fill with the ordinary act of shopping somewhere new.
    """
    history = FakeVendorHistory((10_000, 11_000))
    result = run(
        AccountOutlierCheck().run(snapshot(), FrozenDict({"vendor_history": history}))
    )
    assert result.outcome is CheckOutcome.INCONCLUSIVE


def test_the_check_is_inconclusive_when_architects_history_is_not_wired_in():
    """§4.4 makes this "a genuine consumer of Architect's registry rather than self-contained
    logic". With no provider there is no distribution, and inventing one locally would be this
    package quietly growing its own copy of Architect's learned data."""
    result = run(AccountOutlierCheck().run(snapshot(), EMPTY))
    assert result.outcome is CheckOutcome.INCONCLUSIVE


def test_a_few_large_legitimate_purchases_do_not_stop_a_real_outlier_being_caught():
    """§8's stated reason for choosing IQR over a z-score, made concrete.

    Financial data is "often meaningfully skewed rather than normally distributed (a handful of
    genuinely large legitimate purchases shouldn't blow out a z-score's own assumptions)". A
    z-score's mean and standard deviation are both dragged by the very outliers the check is
    looking for, so after three large purchases the threshold rises high enough that nothing is
    ever an outlier again. Quartiles do not move that way — this history contains two large
    legitimate purchases and the check still catches the genuine one.
    """
    history = FakeVendorHistory((10_000, 11_000, 10_500, 12_000, 900_000, 950_000))
    result = run(
        AccountOutlierCheck().run(
            snapshot(total_centavos=5_000_000), FrozenDict({"vendor_history": history})
        )
    )
    assert result.outcome is CheckOutcome.FLAGGED


def test_quartiles_use_a_stated_interpolation_convention():
    """`docs/PRINCIPLES.md` §3.3: a fence whose position depends on which convention the standard
    library happened to pick is a fence that can move under an interpreter upgrade.

    Written here and pinned, so the threshold a review queue is calibrated against cannot shift
    without a test failing.
    """
    q1, q3 = quartiles((1, 2, 3, 4, 5))
    assert (q1, q3) == (2.0, 4.0)


# ---------------------------------------------------------------------------------------------
# §4.5 — semantic duplicate
# ---------------------------------------------------------------------------------------------


def test_the_same_transaction_uploaded_twice_through_different_channels_is_flagged():
    """§4.5's motivating case: two genuinely different image files, one real-world transaction.

    Ingestion's content-hash dedup cannot see this — different photo, different bytes — which is
    exactly why §4.5 exists as a distinct check.
    """
    other = snapshot(receipt_id="r-2", receipt_number="")
    source = FakeCandidateSource((other,))
    result = run(
        SemanticDuplicateCheck().run(
            snapshot(receipt_number=""), FrozenDict({"duplicate_candidates": source})
        )
    )
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.flag_type == FLAG_TYPES["semantic_duplicate"]


def test_two_receipts_with_different_receipt_numbers_are_never_treated_as_duplicates():
    """The veto, and the reason lunch bought twice in one day is not a finding.

    Two different extracted receipt numbers positively establish two transactions, however well
    vendor, date and amount match. Without this, a coffee bought each morning at the same price
    would be flagged every single day.
    """
    other = snapshot(receipt_id="r-2", receipt_number="OR-000999")
    assert looks_like_same_transaction(snapshot(), other) is False


def test_two_receipts_that_both_lack_a_receipt_number_still_fall_back_to_the_other_fields():
    """Absent numbers prove nothing either way, and must not act as a veto.

    Treating "no number on either" the same as "different numbers" would disable this check for
    exactly the low-quality scans most likely to have been uploaded twice.
    """
    other = snapshot(receipt_id="r-2", receipt_number="")
    assert looks_like_same_transaction(snapshot(receipt_number=""), other) is True


def test_amounts_within_one_percent_match_and_the_relation_is_symmetric():
    """§8's tolerance "allowing for rounding/tax-display differences".

    Symmetry is not decorative: if `a` matched `b` but `b` did not match `a`, whether two
    receipts were duplicates would depend on which one the sweep happened to look at first.
    """
    assert amounts_match(100_000, 100_900) is True
    assert amounts_match(100_900, 100_000) is True
    assert amounts_match(100_000, 102_000) is False
    assert amounts_match(102_000, 100_000) is False


def test_a_receipt_is_never_its_own_duplicate():
    """The obvious bug in a candidate sweep, and it would flag every receipt in the database."""
    source = FakeCandidateSource((snapshot(),))
    result = run(
        SemanticDuplicateCheck().run(snapshot(), FrozenDict({"duplicate_candidates": source}))
    )
    assert result.outcome is CheckOutcome.PASSED


def test_a_duplicate_is_only_ever_flagged_and_never_merged():
    """§8: "never auto-merged regardless of threshold, only ever flagged for review"
    (`docs/PRINCIPLES.md` §4.3).

    Two receipts that look like duplicates may be two genuine transactions at the same shop on
    the same day for the same price — completely ordinary at a convenience store. Auto-merging
    would silently delete a real expense from someone's tax filing.
    """
    other = snapshot(receipt_id="r-2", receipt_number="")
    source = FakeCandidateSource((other,))
    result = run(
        SemanticDuplicateCheck().run(
            snapshot(receipt_number=""), FrozenDict({"duplicate_candidates": source})
        )
    )
    assert result.outcome is CheckOutcome.FLAGGED
    assert "never merged" in result.detail
    assert result.evidence["candidate_ids"] == ("r-2",)


def test_a_different_days_receipt_at_the_same_vendor_and_amount_is_not_a_duplicate():
    """§8's field set requires the same day. A weekly shop for the same basket is not a duplicate."""
    other = snapshot(receipt_id="r-2", transaction_date=date(2026, 3, 7), receipt_number="")
    assert looks_like_same_transaction(snapshot(receipt_number=""), other) is False


# ---------------------------------------------------------------------------------------------
# §4.6 — vendor group and items/vendor mismatch
# ---------------------------------------------------------------------------------------------


def test_a_vendor_filed_under_a_group_its_category_does_not_map_to_is_flagged():
    context = FrozenDict({"expected_group_for_category": {"sundry": "wholesale"}})
    result = run(VendorGroupMismatchCheck().run(snapshot(), context))
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.flag_type == FLAG_TYPES["vendor_group_mismatch"]
    assert "surfaced, not corrected" in result.detail


def test_a_category_missing_from_architects_mapping_is_inconclusive_not_a_mismatch():
    """An unregistered category is Architect's gap to close (§1, `docs/PRINCIPLES.md` §3.4).

    Reporting it as a vendor mismatch would blame the vendor's record for a hole in the taxonomy
    — and would send a human to correct data that is already right.
    """
    context = FrozenDict({"expected_group_for_category": {"hardware": "retail"}})
    result = run(VendorGroupMismatchCheck().run(snapshot(), context))
    assert result.outcome is CheckOutcome.INCONCLUSIVE


def test_a_receipt_whose_items_overwhelmingly_contradict_the_vendor_category_is_flagged():
    """§4.6's own example: grocery items on a receipt from a differently-categorised vendor."""
    result = run(
        ItemsVendorMismatchCheck().run(
            snapshot(item_categories=("hardware", "hardware", "hardware", "hardware")), EMPTY
        )
    )
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.flag_type == FLAG_TYPES["items_vendor_mismatch"]


def test_a_mixed_basket_with_one_odd_item_is_not_a_mismatch():
    """"Strongly suggest" is §4.6's own wording, and the false positives land on ordinary receipts.

    A supermarket receipt legitimately contains a hardware item. A bare-majority threshold would
    flag the weekly shop.
    """
    result = run(
        ItemsVendorMismatchCheck().run(
            snapshot(item_categories=("sundry", "sundry", "sundry", "hardware")), EMPTY
        )
    )
    assert result.outcome is CheckOutcome.PASSED


def test_a_receipt_with_too_few_categorised_items_is_inconclusive():
    """A two-item receipt where both disagree is one line item from a coin flip."""
    result = run(
        ItemsVendorMismatchCheck().run(snapshot(item_categories=("hardware", "hardware")), EMPTY)
    )
    assert result.outcome is CheckOutcome.INCONCLUSIVE


def test_an_items_mismatch_is_surfaced_and_never_recategorises_the_vendor():
    """`docs/PRINCIPLES.md` §4.3. The items might be miscategorised rather than the vendor, and
    nothing here can tell which — guessing would rewrite a vendor's category on the strength of
    one shopping trip."""
    result = run(
        ItemsVendorMismatchCheck().run(
            snapshot(item_categories=("hardware",) * 5), EMPTY
        )
    )
    assert "not recategorised" in result.detail


# ---------------------------------------------------------------------------------------------
# §4.10 — orphaned archive reference
# ---------------------------------------------------------------------------------------------


def test_a_receipt_referencing_a_missing_blob_is_flagged_at_high_severity():
    """§4.10: a receipt row pointing at a `logical_id` with no `BlobLocation` behind it.

    High severity because the original image is the evidence behind a tax filing, and its absence
    is not recoverable by re-running anything.
    """
    checker = FakeBlobLocations(present=set())
    result = run(
        OrphanedArchiveReferenceCheck().run(snapshot(), FrozenDict({"blob_locations": checker}))
    )
    assert result.outcome is CheckOutcome.FLAGGED
    assert result.flag_type == FLAG_TYPES["orphaned_archive_reference"]
    assert result.severity is Severity.HIGH


def test_the_check_finds_the_problem_and_does_not_attempt_a_repair():
    """§4.10's own sketch: "a missing blob for a receipt that's supposedly already processed is
    exactly the kind of thing a human should look at before deciding what to do."

    An automatic repair would have to guess whether the row or the blob is the wrong one, and
    both guesses destroy evidence.
    """
    checker = FakeBlobLocations(present=set())
    result = run(
        OrphanedArchiveReferenceCheck().run(snapshot(), FrozenDict({"blob_locations": checker}))
    )
    assert "found, not repaired" in result.detail


def test_an_unreachable_archive_store_is_inconclusive_and_never_reported_as_a_missing_blob():
    """`docs/PRINCIPLES.md` §4.4, and the most damaging false positive available to this check.

    A transient outage reported as a missing blob would tell a filer their receipt images were
    gone — and a sweep during an outage would say it about every receipt at once.
    """
    checker = FakeBlobLocations(raises=True)
    result = run(
        OrphanedArchiveReferenceCheck().run(snapshot(), FrozenDict({"blob_locations": checker}))
    )
    assert result.outcome is CheckOutcome.INCONCLUSIVE


def test_a_resolvable_archive_reference_passes_and_queried_the_receipts_own_logical_id():
    """§4.10 scopes this to "just this receipt's own logical_id rather than walking the entire
    instance" — the same check as Disaster Recovery's, at routine operating scale."""
    checker = FakeBlobLocations(present={"blob-abc123"})
    result = run(
        OrphanedArchiveReferenceCheck().run(snapshot(), FrozenDict({"blob_locations": checker}))
    )
    assert result.outcome is CheckOutcome.PASSED
    assert checker.queried == ["blob-abc123"]

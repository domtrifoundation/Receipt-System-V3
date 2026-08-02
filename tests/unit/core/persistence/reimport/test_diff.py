"""The field-level diff, and its tolerance for Excel round-trip representation shifts."""

from __future__ import annotations

from decimal import Decimal

from core.persistence.reimport.diff import diff_row, values_equal


def test_identical_rows_produce_no_deltas():
    result = diff_row({"a": 1, "b": "x"}, {"a": 1, "b": "x"}, receipt_id="rc1")
    assert result.is_empty


def test_a_changed_field_is_reported():
    result = diff_row({"vendor_name": "A"}, {"vendor_name": "B"}, receipt_id="rc1")
    assert [d.field for d in result.deltas] == ["vendor_name"]
    assert result.deltas[0].canonical_value == "A"
    assert result.deltas[0].reimported_value == "B"


def test_a_round_tripped_number_is_not_a_user_edit():
    """`Decimal("100.00")` comes back as `100.0` or `"100.00"` depending on cell format.

    Treating that as an edit would manufacture conflicts out of nothing, which is worse than
    missing a change that only differs by formatting.
    """
    assert values_equal(Decimal("100.00"), 100.0)
    assert values_equal(Decimal("100.00"), "100.00")
    assert values_equal("100", 100)
    result = diff_row(
        {"total_amount": Decimal("100.00")}, {"total_amount": 100.0}, receipt_id="rc1"
    )
    assert result.is_empty


def test_a_genuinely_different_number_is_still_a_delta():
    assert not values_equal(Decimal("100.00"), 100.5)
    result = diff_row(
        {"total_amount": Decimal("100.00")}, {"total_amount": 100.5}, receipt_id="rc1"
    )
    assert not result.is_empty


def test_none_is_never_equal_to_a_value():
    assert not values_equal(None, "")
    assert not values_equal("", None)

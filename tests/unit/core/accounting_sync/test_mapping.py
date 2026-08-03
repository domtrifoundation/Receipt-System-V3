"""`map_receipt_to_record` — the pure translation `mapping.py` duck-types against a
`Receipt`-shaped object (deep-dive §1's own "never invents its own vendor identity")."""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.accounting_sync.errors import MappingFailed
from core.accounting_sync.mapping import map_receipt_to_record


def test_maps_a_well_formed_receipt(fake_receipt):
    record = map_receipt_to_record(fake_receipt)

    assert record.receipt_id == fake_receipt.receipt_id
    assert record.vendor_name == "Acme Corp"
    assert record.total_amount == "12.50"
    assert record.currency == "PHP"


def test_vendor_display_name_overrides_the_receipt_own_vendor_name(fake_receipt):
    record = map_receipt_to_record(fake_receipt, vendor_display_name="Corrected Vendor Inc.")

    assert record.vendor_name == "Corrected Vendor Inc."


def test_raises_mapping_failed_when_vendor_name_is_missing(fake_receipt):
    receipt = replace(fake_receipt, vendor_name="")

    with pytest.raises(MappingFailed):
        map_receipt_to_record(receipt)


def test_raises_mapping_failed_when_total_amount_is_missing(fake_receipt):
    receipt = replace(fake_receipt, total_amount=None)

    with pytest.raises(MappingFailed):
        map_receipt_to_record(receipt)


def test_raises_mapping_failed_when_transaction_date_is_missing(fake_receipt):
    receipt = replace(fake_receipt, transaction_date=None)

    with pytest.raises(MappingFailed):
        map_receipt_to_record(receipt)


def test_category_read_from_fields_when_present(fake_receipt):
    receipt = replace(fake_receipt, fields={"category": "Office Supplies"})

    record = map_receipt_to_record(receipt)

    assert record.category == "Office Supplies"

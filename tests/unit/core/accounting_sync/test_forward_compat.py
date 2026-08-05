"""Forward-Compatibility Pattern applicability (`docs/PRINCIPLES.md` §2.1) — this
folder's `CLAUDE.md` states it applies; this test locks that down against the one real
dict-typed field this package has, `MappedRecord.extra`."""

from __future__ import annotations

import collections.abc

import pytest

from common.frozen_dict import FrozenDict
from core.accounting_sync.contracts import MappedRecord, SyncErrorCode


@pytest.mark.forward_compat
def test_mapped_record_extra_defaults_to_a_frozen_dict_not_a_plain_dict():
    from datetime import datetime, timezone

    record = MappedRecord(
        receipt_id="r1", vendor_name="Acme", transaction_date=datetime.now(timezone.utc),
        total_amount="1.00", currency="PHP",
    )

    assert isinstance(record.extra, collections.abc.Mapping)
    assert type(record.extra) is FrozenDict


@pytest.mark.forward_compat
def test_mapped_record_extra_rejects_mutation():
    from datetime import datetime, timezone

    record = MappedRecord(
        receipt_id="r1", vendor_name="Acme", transaction_date=datetime.now(timezone.utc),
        total_amount="1.00", currency="PHP", extra=FrozenDict({"line_items": "2"}),
    )

    with pytest.raises(Exception):  # noqa: B017,PT011 - FrozenDict's own immutability error, not asserted by name here
        record.extra["line_items"] = "3"


def test_sync_error_code_is_a_real_enum_not_a_bare_string():
    assert SyncErrorCode.RECEIPT_FLAGGED.value == "receipt_flagged"

"""Shared test doubles and helpers for Reconciliation's suite.

Every fixture receipt in this suite is **invented**. `tests/fixtures/real_receipts/` holds 701
genuine Philippine receipts carrying real TINs, real vendor relationships and real purchase
histories; it is gitignored and this repository is public. Nothing in these tests reads from it
or copies a value out of it — the TINs below are structurally valid and belong to nobody.

`test_doubles_conform.py` asserts each fake here satisfies the `Protocol` in `contracts.py` it
stands in for, because a fake whose signature has drifted makes the whole suite pass against an
interface no production caller uses.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from core.reconciliation.contracts import ReceiptSnapshot, VATABLE


def run(coro):
    """Drive one coroutine to completion.

    `pytest-asyncio` is deliberately not a dependency of this project, so every async test in
    this repo goes through a helper like this one rather than a plugin.
    """
    return asyncio.run(coro)


#: A structurally valid, entirely invented TIN. Nine base digits plus a three-digit branch code.
FAKE_TIN = "123-456-789-000"

UPLOADED_AT = datetime(2026, 3, 15, 9, 0, 0, tzinfo=timezone.utc)
TRANSACTION_DATE = date(2026, 3, 14)


def snapshot(**overrides) -> ReceiptSnapshot:
    """A receipt that passes every check, with named overrides for the one under test.

    Starting from clean and breaking exactly one field is what makes each test's assertion
    attributable: a fixture that was already failing three checks would let a fourth failure go
    unnoticed.
    """
    defaults = dict(
        receipt_id="r-1",
        vendor_name="Sari-Sari Store Uno",
        vendor_tin=FAKE_TIN,
        transaction_date=TRANSACTION_DATE,
        uploaded_at=UPLOADED_AT,
        subtotal_centavos=100_000,
        vat_centavos=12_000,
        total_centavos=112_000,
        vat_treatment=VATABLE,
        receipt_number="OR-000123",
        atp_number="ATP-2024-001",
        atp_valid_from=date(2024, 1, 1),
        atp_valid_until=date(2029, 1, 1),
        address="123 Rizal Avenue, Quezon City",
        logical_id="blob-abc123",
        item_categories=("sundry", "sundry", "sundry"),
        vendor_category="sundry",
        vendor_group="retail",
    )
    defaults.update(overrides)
    return ReceiptSnapshot(**defaults)


class FakeVendorHistory:
    """A `VendorHistoryProvider` returning a fixed distribution of past amounts."""

    def __init__(self, amounts: tuple[int, ...] = ()) -> None:
        self.amounts = amounts
        self.calls: list[tuple[str, str]] = []

    async def historical_amounts(self, vendor_name, category):
        self.calls.append((vendor_name, category))
        return self.amounts


class FakeBlobLocations:
    """A `BlobLocationChecker` standing in for Disaster Recovery's own verification."""

    def __init__(self, present: set[str] | None = None, *, raises: bool = False) -> None:
        self.present = present if present is not None else set()
        self._raises = raises
        self.queried: list[str] = []

    async def blob_exists(self, logical_id):
        self.queried.append(logical_id)
        if self._raises:
            raise RuntimeError("archive store unreachable")
        return logical_id in self.present


class FakeCandidateSource:
    """A `DuplicateCandidateSource` returning a fixed candidate set."""

    def __init__(self, candidates: tuple[ReceiptSnapshot, ...] = ()) -> None:
        self.candidates = candidates

    async def candidates_for(self, snapshot):
        return self.candidates


class RecordingFlagEmitter:
    """A `FlagEmitter` that remembers every flag it was asked to create."""

    def __init__(self, *, raises: bool = False) -> None:
        self.flags: list[tuple[str, str, object]] = []
        self._raises = raises

    async def create_flag(self, receipt_id, flag_type, details=None):
        if self._raises:
            raise RuntimeError("review queue unreachable")
        self.flags.append((receipt_id, flag_type, details))


class RecordingWriter:
    """A `ReceiptWriter` that records applied corrections and can report a conflict.

    `conflicting` names the receipts whose current value disagrees with the correction — the
    §4.3 case that must be surfaced rather than overwritten.
    """

    def __init__(self, conflicting: set[str] | None = None, *, raises_on: str = "") -> None:
        self.applied: list[tuple[str, object]] = []
        self.conflicting = conflicting if conflicting is not None else set()
        self._raises_on = raises_on

    async def apply_correction(self, receipt_id, change):
        if receipt_id == self._raises_on:
            raise RuntimeError("persistence outage")
        if receipt_id in self.conflicting:
            return False, f"{receipt_id} was already corrected by hand"
        self.applied.append((receipt_id, change))
        return True, ""


__all__ = [
    "FAKE_TIN",
    "FakeBlobLocations",
    "FakeCandidateSource",
    "FakeVendorHistory",
    "RecordingFlagEmitter",
    "RecordingWriter",
    "TRANSACTION_DATE",
    "UPLOADED_AT",
    "run",
    "snapshot",
]

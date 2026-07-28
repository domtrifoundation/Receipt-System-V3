"""Contract-shape guarantees: frozen, `FrozenDict`-typed, and Mapping-checked."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

import pytest

from common.frozen_dict import FrozenDict
from core.persistence import contracts
from core.persistence.errors import ERROR_HINTS

_CONTRACT_TYPES = [
    contracts.BlobRef,
    contracts.BlobLocation,
    contracts.BackupConfirmation,
    contracts.BlobWriteResult,
    contracts.BlobReadResult,
    contracts.ReferenceIdentifier,
    contracts.Receipt,
    contracts.WriteResult,
    contracts.ReceiptReadResult,
    contracts.ExportSnapshotRef,
]


@pytest.mark.parametrize("cls", _CONTRACT_TYPES)
def test_every_contract_is_frozen(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen, f"{cls.__name__} must be frozen"


def test_receipt_fields_default_is_a_frozen_dict():
    receipt = contracts.Receipt(
        receipt_id="r",
        user_id="u",
        blob=contracts.BlobRef("a" * 64),
        created_at=contracts.utcnow(),
        updated_at=contracts.utcnow(),
    )
    assert isinstance(receipt.fields, FrozenDict)
    with pytest.raises(Exception):
        receipt.fields["injected"] = "value"  # type: ignore[index]


@pytest.mark.forward_compat
def test_frozen_dict_is_a_mapping_but_may_not_be_a_dict():
    """The specific 3.15 trap, asserted rather than trusted.

    The builtin `frozendict` (PEP 814) inherits from `object`, not `dict`, so
    `isinstance(x, dict)` silently returns False for it and any code gated on that check
    takes the wrong branch. Every check in this package tests `collections.abc.Mapping`,
    which holds on every interpreter in the support matrix — that is what this asserts.
    """
    value = FrozenDict({"engine": "tesseract", "mean_confidence": 0.87})
    assert isinstance(value, Mapping)
    assert dict(value)["engine"] == "tesseract"


@pytest.mark.forward_compat
def test_module_level_constant_tables_are_frozen_dicts():
    """`docs/PRINCIPLES.md` §2.1.1 — a constant lookup table is `FrozenDict`, not `dict`."""
    assert isinstance(ERROR_HINTS, FrozenDict)
    assert isinstance(ERROR_HINTS, Mapping)


def test_logical_id_and_physical_hash_are_separate_fields():
    """The correctness point this API has already been gotten wrong on once.

    `BlobRef` carries identity and nothing else. `BlobLocation` carries the physical address.
    A `BlobRef` growing a `physical_hash` or a `codec` field is the regression this guards.
    """
    ref_fields = {f.name for f in dataclasses.fields(contracts.BlobRef)}
    assert ref_fields == {"logical_id"}
    location_fields = {f.name for f in dataclasses.fields(contracts.BlobLocation)}
    assert {"logical_id", "physical_hash", "codec"} <= location_fields
    assert "physical_hash" not in ref_fields
    assert "stored_encoding" not in ref_fields

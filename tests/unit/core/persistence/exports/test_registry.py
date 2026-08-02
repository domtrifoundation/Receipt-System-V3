"""The export Provider Registry, plus the two format tests that need no optional dependency.

The registry tests matter more than any individual format here: the framework's whole reason
for existing is that adding a format is registering a provider, never editing a dispatch
branch. A registry that silently swallowed an unknown name, or that let one bad provider
break the caller, would undo that.
"""

from __future__ import annotations

import pytest

from common.frozen_dict import FrozenDict
from core.persistence.blob_store.store import BlobStore
from core.persistence.contracts import BlobRef
from core.persistence.db.receipts import ReceiptRepository
from core.persistence.exports import errors
from core.persistence.exports.contracts import ExportProvider, ExportResult
from core.persistence.exports.providers import build_default_registry, build_context
from core.persistence.exports.providers.audit_package import ARCHIVE_LIMITS, check_archive
from core.persistence.exports.providers.slsp_summary import (
    FALLBACK_THRESHOLDS,
    SlspSummaryProvider,
    render_dat,
)
from core.persistence.exports.registry import DEFAULT_PROVIDER_MODULES, ExportRegistry

from ..conftest import make_receipt, run


class _StubProvider:
    name = "stub"
    format = "txt"

    async def generate(self, user_id, params):
        return ExportResult(ok=True, format=self.format, export_blob_ref=BlobRef("a" * 64))


class _ExplodingProvider:
    name = "exploding"
    format = "txt"

    async def generate(self, user_id, params):
        raise RuntimeError("provider blew up")


def test_a_provider_satisfies_the_protocol_structurally():
    assert isinstance(_StubProvider(), ExportProvider)


def test_registering_a_provider_is_all_it_takes():
    registry = ExportRegistry([_StubProvider()])
    assert registry.names() == ("stub",)
    result = run(registry.generate("stub", "user-1"))
    assert result.ok and result.format == "txt"


def test_an_unknown_provider_is_an_error_code_not_a_raise():
    registry = ExportRegistry()
    result = run(registry.generate("nope", "user-1"))
    assert not result.ok
    assert result.error_code == errors.UNKNOWN_PROVIDER


def test_one_failing_provider_does_not_break_the_caller():
    registry = ExportRegistry([_ExplodingProvider()])
    result = run(registry.generate("exploding", "user-1"))
    assert not result.ok
    assert result.error_code == errors.GENERATION_FAILED
    assert "blew up" in result.error_detail


def test_the_default_roster_registers_every_named_provider(db, tmp_path):
    ctx = build_context(db, BlobStore(db, tmp_path / "blobs"))
    registry = build_default_registry(ctx)
    assert set(registry.names()) == set(DEFAULT_PROVIDER_MODULES)


def test_provider_module_table_is_a_frozen_dict():
    assert isinstance(DEFAULT_PROVIDER_MODULES, FrozenDict)


def test_csv_and_iif_providers_need_no_optional_dependency(db, tmp_path):
    ctx = build_context(db, BlobStore(db, tmp_path / "blobs"))
    run(ReceiptRepository(db).save(make_receipt(), actor="worker"))
    registry = build_default_registry(ctx)

    for name in ("xero", "quickbooks"):
        result = run(registry.generate(name, "user-1"))
        assert result.ok, f"{name}: {result.error_code} {result.error_detail}"
        assert result.export_blob_ref is not None


def test_group_export_denies_when_no_permission_check_is_configured(db, tmp_path):
    """An unchecked permission is a denial, never a default allow."""
    ctx = build_context(db, BlobStore(db, tmp_path / "blobs"))
    registry = build_default_registry(ctx)
    result = run(
        registry.generate("group_export", "user-1", FrozenDict({"group_id": "g1"}))
    )
    assert not result.ok
    assert result.error_code == errors.ACCESS_DENIED


def test_slsp_thresholds_come_from_config_not_a_hardcoded_constant(db, tmp_path):
    """The threshold-currency hook (§10 of the export deep-dive).

    A configured value must win over the fallback table, so a BIR revision is a config
    change rather than a code change.
    """
    ctx = build_context(db, BlobStore(db, tmp_path / "blobs"))
    default = SlspSummaryProvider(ctx)
    configured = SlspSummaryProvider(ctx, FrozenDict({"sales": "9999999", "purchases": "1"}))

    assert str(default.threshold("sales")) == FALLBACK_THRESHOLDS["sales"]
    assert str(configured.threshold("sales")) == "9999999"
    assert str(configured.threshold("purchases")) == "1"


def test_dat_rendering_requires_a_supplied_layout():
    """The layout is reverse-engineered from a real sample and passed in. Never invented."""
    rendered = render_dat(
        (make_receipt(),), "|registered_name,gross_amount,vat_amount", "purchases"
    )
    assert rendered.decode().strip() == "Vendor A|100.00|12.00"


def test_outbound_archive_checks_are_the_same_shape_as_inbound_ones():
    """Symmetry, resolved in §11: the generating side is guarded, not trusted."""
    assert check_archive(compressed=1000, uncompressed=2000, entries=10) == ""
    assert check_archive(1, 10**9, 10) != ""
    assert check_archive(1000, 2000, ARCHIVE_LIMITS["max_entries"] + 1) != ""


def test_archive_limits_table_is_a_frozen_dict():
    assert isinstance(ARCHIVE_LIMITS, FrozenDict)

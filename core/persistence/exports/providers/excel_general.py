"""The general-purpose, print-friendly Excel export (§3).

This provider and Reimport's parser are a **matched pair**: this one writes the hidden
snapshot-reference cell, that one reads it. A change to either half without the other breaks
the round trip, so the cell's sheet/address/prefix constants live in exactly one place
(`reimport/parser.py`) and both halves import them from there.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import ExportResult
from ..errors import ExportError, ProviderUnavailable
from . import common


class ExcelGeneralProvider:
    """Implements `ExportProvider`."""

    name = "excel_general"
    format = "xlsx"

    def __init__(self, ctx: common.ExportContext) -> None:
        self._ctx = ctx

    async def generate(self, user_id: str, params: FrozenDict) -> ExportResult:
        receipts = await common.fetch_receipts(self._ctx, user_id, params)
        export_id = common.new_export_id()
        try:
            data = common.build_workbook(receipts, export_id=export_id)
            blob = await common.store_artifact(self._ctx, data)
        except (ProviderUnavailable, ExportError) as exc:
            return ExportResult(ok=False, error_code=exc.code, error_detail=str(exc))
        generated_at = await common.record_snapshot(self._ctx, export_id, user_id)
        return ExportResult(
            ok=True,
            export_blob_ref=blob,
            format=self.format,
            generated_at=generated_at,
            export_id=export_id,
            extra_artifacts=FrozenDict({"receipt_count": len(receipts)}),
        )


__all__ = ["ExcelGeneralProvider"]

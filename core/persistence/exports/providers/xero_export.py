"""One-time Xero CSV import file (§8).

Same standing as `quickbooks_export.py`: a downloadable file the user imports themselves,
kept deliberately outside the live accounting-sync API's credentialed, ongoing scope. `csv`
is stdlib, so this provider has no optional dependency and nothing to degrade.
"""

from __future__ import annotations

import csv
import io

from common.frozen_dict import FrozenDict

from ..contracts import ExportResult
from ..errors import ExportError
from . import common

#: Xero's bills-import column order. A module-level constant, so a `FrozenDict` is not the
#: right shape here — this is an ordered sequence, and a tuple already says "constant".
XERO_COLUMNS = (
    "*ContactName",
    "*InvoiceNumber",
    "*InvoiceDate",
    "*DueDate",
    "Description",
    "*Quantity",
    "*UnitAmount",
    "*AccountCode",
    "TaxAmount",
    "Currency",
)


class XeroExportProvider:
    """Implements `ExportProvider`."""

    name = "xero"
    format = "csv"

    def __init__(self, ctx: common.ExportContext, account_code: str = "400") -> None:
        self._ctx = ctx
        self._account_code = account_code

    async def generate(self, user_id: str, params: FrozenDict) -> ExportResult:
        receipts = await common.fetch_receipts(self._ctx, user_id, params)
        account_code = str(params.get("account_code", self._account_code))
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(XERO_COLUMNS)
        for receipt in receipts:
            date = (
                receipt.transaction_date.date().isoformat()
                if receipt.transaction_date
                else ""
            )
            writer.writerow(
                [
                    receipt.vendor_name,
                    receipt.receipt_id,
                    date,
                    date,
                    f"Receipt {receipt.receipt_id}",
                    1,
                    str(receipt.total_amount or "0"),
                    account_code,
                    str(receipt.vat_amount or "0"),
                    receipt.currency,
                ]
            )
        try:
            blob = await common.store_artifact(self._ctx, buffer.getvalue().encode("utf-8"))
        except ExportError as exc:
            return ExportResult(ok=False, error_code=exc.code, error_detail=str(exc))
        export_id = common.new_export_id()
        generated_at = await common.record_snapshot(self._ctx, export_id, user_id)
        return ExportResult(
            ok=True,
            export_blob_ref=blob,
            format=self.format,
            generated_at=generated_at,
            export_id=export_id,
            extra_artifacts=FrozenDict({"receipt_count": len(receipts)}),
        )


__all__ = ["XERO_COLUMNS", "XeroExportProvider"]

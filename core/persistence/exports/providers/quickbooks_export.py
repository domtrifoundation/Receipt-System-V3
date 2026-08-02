"""One-time QuickBooks IIF file (§8).

The genuinely simple half of accounting integration: a file the user downloads and imports
manually, no OAuth and no ongoing connection. **Deliberately separate from the live-sync
API** — that one owns credentialed, ongoing push; this is just another export format
alongside the Excel and SLSP ones, reusing this framework's own pull-format-done pattern
rather than being drawn into the more complex integration's scope.

IIF is tab-delimited with a header block naming each row type. No external library is needed
or wanted for a format this simple, so there is no optional dependency to degrade here.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import ExportResult
from ..errors import ExportError
from . import common

IIF_HEADER = (
    "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO\n"
    "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO\n"
    "!ENDTRNS\n"
)


class QuickBooksExportProvider:
    """Implements `ExportProvider`."""

    name = "quickbooks"
    format = "iif"

    def __init__(self, ctx: common.ExportContext, expense_account: str = "Expenses"):
        self._ctx = ctx
        self._account = expense_account

    async def generate(self, user_id: str, params: FrozenDict) -> ExportResult:
        receipts = await common.fetch_receipts(self._ctx, user_id, params)
        account = str(params.get("expense_account", self._account))
        lines = [IIF_HEADER]
        for receipt in receipts:
            date = (
                receipt.transaction_date.strftime("%m/%d/%Y")
                if receipt.transaction_date
                else ""
            )
            amount = str(receipt.total_amount or "0")
            memo = receipt.receipt_id
            lines.append(
                f"TRNS\tBILL\t{date}\tAccounts Payable\t{receipt.vendor_name}\t"
                f"-{amount}\t{memo}\n"
                f"SPL\tBILL\t{date}\t{account}\t{receipt.vendor_name}\t{amount}\t{memo}\n"
                "ENDTRNS\n"
            )
        try:
            blob = await common.store_artifact(self._ctx, "".join(lines).encode("utf-8"))
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


__all__ = ["IIF_HEADER", "QuickBooksExportProvider"]

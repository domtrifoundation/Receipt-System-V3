"""BIR Summary List of Sales / Purchases (§4).

**SLSP is two separate lists, not one document**: the SLS and the SLP, submitted together
but structurally independent, filed quarterly alongside VAT Form 2550Q. This provider
produces both plus a review copy — several artifacts from one call, not several registered
export types.

**Thresholds come from config, never from a constant in this file** (§10's own test). The
current values are ₱2,500,000 in quarterly sales/receipts for the sales list and ₱1,000,000
in quarterly purchases net of VAT for the purchases list, and they are Telemetrees-tracked
regulatory facts precisely because BIR can revise them. The table below is a fallback for an
install with no config, not the authority.

**The DAT layout is deliberately not guessed at.** The byte-level field-order/delimiter
specification is genuinely not public — a Freedom-of-Information request for RMC-24-2002's
Annexes A–F was denied, which is confirmed evidence rather than an unfinished lookup.
Emitting a plausible-looking file for a tax submission would be worse than emitting none, so
without a configured, reverse-engineered layout this provider returns the `.xlsx` review copy
and reports `export_spec_unavailable` for the `.dat` half. Passing `dat_layout` in params —
derived from a real, valid sample file — is what turns the DAT half on.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from common.frozen_dict import FrozenDict

from ..contracts import ExportResult
from ..errors import ExportError, ProviderUnavailable, SpecUnavailable
from . import common

#: Fallback thresholds in pesos. A module-level constant lookup table, therefore a
#: `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1).
FALLBACK_THRESHOLDS = FrozenDict(
    {
        "sales": "2500000",
        "purchases": "1000000",
    }
)

#: Required per-entry fields per current BIR guidance. The VAT amount is broken out
#: separately rather than folded into the gross — that separation is the requirement itself.
REQUIRED_ENTRY_FIELDS = ("tin", "registered_name", "gross_amount", "vat_amount")


class SlspSummaryProvider:
    """Implements `ExportProvider`."""

    name = "slsp_summary"
    format = "slsp"

    def __init__(
        self, ctx: common.ExportContext, thresholds: FrozenDict | None = None
    ) -> None:
        self._ctx = ctx
        #: Injected from config. Defaulting to the fallback table is a degradation, and the
        #: threshold-currency test is what confirms a configured value actually wins.
        self._thresholds = thresholds or FALLBACK_THRESHOLDS

    async def generate(self, user_id: str, params: FrozenDict) -> ExportResult:
        receipts = await common.fetch_receipts(self._ctx, user_id, params)
        export_id = common.new_export_id()
        try:
            xlsx = common.build_workbook(receipts, export_id=export_id)
            review_copy = await common.store_artifact(self._ctx, xlsx)
        except (ProviderUnavailable, ExportError) as exc:
            return ExportResult(ok=False, error_code=exc.code, error_detail=str(exc))
        generated_at = await common.record_snapshot(self._ctx, export_id, user_id)

        purchases_net = sum(
            ((r.total_amount or Decimal(0)) - (r.vat_amount or Decimal(0)) for r in receipts),
            Decimal(0),
        )
        sales_total = Decimal(str(params.get("quarterly_sales", "0")))
        crosses_purchases = purchases_net > self.threshold("purchases")
        crosses_sales = sales_total > self.threshold("sales")

        artifacts: dict[str, Any] = {
            "purchases_net_of_vat": str(purchases_net),
            "crosses_sales_threshold": crosses_sales,
            "crosses_purchases_threshold": crosses_purchases,
        }
        error_code = ""
        error_detail = ""
        layout = params.get("dat_layout", "")

        if crosses_sales or crosses_purchases:
            if not layout:
                error_code = SpecUnavailable.code
                error_detail = (
                    "a threshold was crossed but no validated DAT layout is configured; the "
                    ".xlsx review copy was produced and the .dat files deliberately were not"
                )
            else:
                if crosses_sales:
                    blob = await common.store_artifact(
                        self._ctx, render_dat(receipts, layout, "sales")
                    )
                    artifacts["sls_dat"] = blob.logical_id
                if crosses_purchases:
                    blob = await common.store_artifact(
                        self._ctx, render_dat(receipts, layout, "purchases")
                    )
                    artifacts["slp_dat"] = blob.logical_id

        return ExportResult(
            ok=True,
            export_blob_ref=review_copy,
            format=self.format,
            generated_at=generated_at,
            export_id=export_id,
            extra_artifacts=FrozenDict(artifacts),
            error_code=error_code,
            error_detail=error_detail,
        )

    def threshold(self, which: str) -> Decimal:
        return Decimal(str(self._thresholds.get(which, FALLBACK_THRESHOLDS[which])))


def render_dat(receipts, layout: str, which: str) -> bytes:
    """Render one DAT file against a *supplied* layout.

    `layout` is `<delimiter><comma-separated field order>` — a value obtained by reverse
    engineering a real, valid sample DAT file, never invented here. That is precisely what
    the `SpecUnavailable` path above exists to protect.
    """
    delimiter = layout[0] if layout else ","
    fields = [f.strip() for f in layout[1:].split(",") if f.strip()] or list(
        REQUIRED_ENTRY_FIELDS
    )
    lines = []
    for receipt in receipts:
        row = {
            "tin": "",
            "registered_name": receipt.vendor_name,
            "gross_amount": str(receipt.total_amount or ""),
            "vat_amount": str(receipt.vat_amount or ""),
            "kind": which,
        }
        lines.append(delimiter.join(row.get(f, "") for f in fields))
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


__all__ = ["FALLBACK_THRESHOLDS", "REQUIRED_ENTRY_FIELDS", "SlspSummaryProvider", "render_dat"]

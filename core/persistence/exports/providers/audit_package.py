"""Bundled evidence export — images, filtered history, and a summary sheet (§5).

Everything an auditor would plausibly want in one download, assembled from mechanisms that
already exist rather than growing logic of its own.

**Outbound archive checks are symmetric with inbound ones** (§11's resolution). Content
Security applies compression-ratio, cumulative-size and entry-count checks to archives coming
*in*; the same checks apply to this bundle going *out*. The risk is genuinely the same — a
mistakenly degenerate bundle — and there is no real cost to guarding the generating side
rather than trusting it never produces something pathological. A bundle that trips its own
checks is reported, not shipped.
"""

from __future__ import annotations

import io
import json
import zipfile

from common.frozen_dict import FrozenDict

from ..contracts import ExportResult
from ..errors import ARCHIVE_CHECK_FAILED, ExportError, ProviderUnavailable
from . import common

#: The outbound guard's own bounds. A module-level constant table, so `FrozenDict` (§2.1.1).
#: These mirror what Content Security applies inbound; when that API lands they should be
#: read from it rather than restated, and this table becomes the fallback.
ARCHIVE_LIMITS = FrozenDict(
    {
        "max_entries": 5000,
        "max_uncompressed_bytes": 2 * 1024**3,
        "max_compression_ratio": 200,
    }
)


class AuditPackageProvider:
    """Implements `ExportProvider`."""

    name = "audit_package"
    format = "zip"

    def __init__(self, ctx: common.ExportContext) -> None:
        self._ctx = ctx

    async def generate(self, user_id: str, params: FrozenDict) -> ExportResult:
        receipts = await common.fetch_receipts(self._ctx, user_id, params)
        export_id = common.new_export_id()
        buffer = io.BytesIO()
        uncompressed = 0
        entries = 0

        try:
            summary = common.build_workbook(receipts, export_id=export_id)
        except ProviderUnavailable as exc:
            return ExportResult(ok=False, error_code=exc.code, error_detail=str(exc))

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("summary.xlsx", summary)
            uncompressed += len(summary)
            entries += 1
            for receipt in receipts:
                read = await self._ctx.blobs.get(receipt.blob.logical_id)
                if not read.ok:
                    # A missing image degrades the bundle, never fails it — an auditor is
                    # better served by the rest of the evidence plus an explicit note.
                    bundle.writestr(
                        f"images/{receipt.receipt_id}.MISSING.txt",
                        f"{read.error_code}: {read.error_detail}",
                    )
                    entries += 1
                    continue
                suffix = read.location.codec.value if read.location else "bin"
                bundle.writestr(f"images/{receipt.receipt_id}.{suffix}", read.data)
                uncompressed += len(read.data)
                entries += 1
                history = await self._ctx.history.get_receipt_history(receipt.receipt_id)
                payload = json.dumps(
                    [
                        {"event_id": e.event_id, "occurred_at": e.occurred_at.isoformat(),
                         "summary": getattr(e, "summary", ""),
                         "actor": getattr(e, "actor", "")}
                        for e in history
                    ],
                    indent=2,
                )
                bundle.writestr(f"history/{receipt.receipt_id}.json", payload)
                uncompressed += len(payload)
                entries += 1

        data = buffer.getvalue()
        breach = check_archive(len(data), uncompressed, entries)
        if breach:
            return ExportResult(
                ok=False, error_code=ARCHIVE_CHECK_FAILED, error_detail=breach
            )

        try:
            blob = await common.store_artifact(self._ctx, data)
        except ExportError as exc:
            return ExportResult(ok=False, error_code=exc.code, error_detail=str(exc))
        generated_at = await common.record_snapshot(self._ctx, export_id, user_id)
        return ExportResult(
            ok=True,
            export_blob_ref=blob,
            format=self.format,
            generated_at=generated_at,
            export_id=export_id,
            extra_artifacts=FrozenDict({"entries": entries, "receipt_count": len(receipts)}),
        )


def check_archive(compressed: int, uncompressed: int, entries: int) -> str:
    """The same three checks Content Security applies inbound. Empty string means clean."""
    if entries > ARCHIVE_LIMITS["max_entries"]:
        return f"{entries} entries exceeds the outbound bundle limit"
    if uncompressed > ARCHIVE_LIMITS["max_uncompressed_bytes"]:
        return f"{uncompressed} uncompressed bytes exceeds the outbound bundle limit"
    if compressed > 0 and uncompressed / compressed > ARCHIVE_LIMITS["max_compression_ratio"]:
        return "compression ratio exceeds the outbound bundle limit"
    return ""


__all__ = ["ARCHIVE_LIMITS", "AuditPackageProvider", "check_archive"]

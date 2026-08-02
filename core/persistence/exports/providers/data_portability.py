"""Account Guardian's data-portability dump (§6).

Account Guardian's own deep-dive (§6.2) already specified reusing this framework rather than
inventing a parallel data-dump path; this file is the concrete provider that pointer refers
to. **Full account scope**, not the curated business view `excel_general.py` produces — every
table holding this user's own data, including their history, because "everything we hold about
you" is the actual promise a portability export makes.

Scope stops exactly at the per-user boundary. `GLOBAL`-layer data — Architect's shared vendor
directory and moderation queue, temporal_learning's promoted facts — is not this user's data
to export, and the same per-user database boundary that makes isolation structural (§4.5)
makes that scoping structural here too rather than a filter someone could get wrong.
"""

from __future__ import annotations

import io
import json
import zipfile

from common.frozen_dict import FrozenDict

from ..contracts import ExportResult
from ..errors import ExportError
from . import common

#: Every per-user table included in a portability dump. A module-level constant, so a
#: `FrozenDict` (§2.1.1). Adding a per-user table means adding it here in the same PR — a
#: portability export that silently omits a table is a compliance problem, not a gap.
PORTABLE_TABLES = FrozenDict(
    {
        "receipts": "SELECT * FROM receipts WHERE user_id = ?",
        "reference_identifiers": (
            "SELECT ri.* FROM reference_identifiers ri JOIN receipts r"
            " ON r.receipt_id = ri.receipt_id WHERE r.user_id = ?"
        ),
        "historian_events": (
            "SELECT h.* FROM historian_events h JOIN receipts r ON r.receipt_id = h.row_id"
            " WHERE r.user_id = ?"
        ),
        "narrative_events": (
            "SELECT n.* FROM narrative_events n JOIN receipts r"
            " ON r.receipt_id = n.receipt_id WHERE r.user_id = ?"
        ),
        "blob_locations": (
            "SELECT b.* FROM blob_locations b JOIN receipts r ON r.logical_id = b.logical_id"
            " WHERE r.user_id = ?"
        ),
    }
)


class DataPortabilityProvider:
    """Implements `ExportProvider`."""

    name = "data_portability"
    format = "zip"

    def __init__(self, ctx: common.ExportContext) -> None:
        self._ctx = ctx

    async def generate(self, user_id: str, params: FrozenDict) -> ExportResult:
        tables = await self._dump_tables(user_id)
        receipts = await common.fetch_receipts(self._ctx, user_id, params)
        export_id = common.new_export_id()

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
            for table, rows in tables.items():
                bundle.writestr(
                    f"data/{table}.json", json.dumps(rows, indent=2, default=str)
                )
            for receipt in receipts:
                read = await self._ctx.blobs.get(receipt.blob.logical_id)
                if read.ok and read.location is not None:
                    bundle.writestr(
                        f"images/{receipt.receipt_id}.{read.location.codec.value}", read.data
                    )

        try:
            blob = await common.store_artifact(self._ctx, buffer.getvalue())
        except ExportError as exc:
            return ExportResult(ok=False, error_code=exc.code, error_detail=str(exc))
        generated_at = await common.record_snapshot(self._ctx, export_id, user_id)
        return ExportResult(
            ok=True,
            export_blob_ref=blob,
            format=self.format,
            generated_at=generated_at,
            export_id=export_id,
            extra_artifacts=FrozenDict({t: len(r) for t, r in tables.items()}),
        )

    async def _dump_tables(self, user_id: str) -> dict[str, list[dict]]:
        def _read(conn) -> dict[str, list[dict]]:
            out: dict[str, list[dict]] = {}
            for table, sql in PORTABLE_TABLES.items():
                rows = conn.execute(sql, (user_id,)).fetchall()
                out[table] = [dict(r) for r in rows]
            return out

        return await self._ctx.db.run(_read)


__all__ = ["PORTABLE_TABLES", "DataPortabilityProvider"]

"""Reimport orchestration: scan gate → parse → baseline → resolve → write → flag (§4, §5).

This is the only module in the sub-API that touches the database, raises a flag, or knows
what order things happen in. `three_way_diff.py` stays a pure function so its resolution
matrix is directly testable, and `parser.py` stays a pure reader.

**Three things here are not negotiable:**

1. **The content scan is a fail-closed gate.** An unscanned file is treated as unsafe, full
   stop (`docs/PRINCIPLES.md` §4.2). Being "the user's own file coming back" earns a
   reimport no trust at all — Content Security scans it exactly like any other untrusted
   external upload.
2. **Actor tagging is `human:<user_id>-via-reimport`**, distinguishable from a direct in-app
   edit by the same user (§5). The provenance — came back through a downloaded-then-
   reuploaded file rather than live editing — is genuinely useful audit context.
3. **A conflict never blocks the rest of the reimport and never resolves itself.** Clean
   fields apply; conflicting fields keep canonical and surface as one `reimport_conflict`
   flag. No automatic last-write-wins, and no rejecting the whole file over one field.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from common.frozen_dict import FrozenDict

from ..contracts import ExportSnapshotRef
from ..db.connection import Database
from ..db.receipts import ReceiptRepository, receipt_to_row
from ..historian.query import HistorianQuery
from . import errors
from .contracts import FieldConflict, ReimportRequest, ReimportResult
from .parser import parse_workbook
from .three_way_diff import three_way_resolve


class FlagSink(Protocol):
    """Review/Flagging's own entry point, behind one small interface (§1.3).

    Review/Flagging is a separate API and a separate process; this is the seam. A `None`
    sink means the flag could not be raised, which is reported honestly in the result rather
    than swallowed — a conflict a human never hears about is the failure mode §4.3 exists to
    prevent, so it must not be silently possible.
    """

    async def raise_flag(
        self, flag_type: str, user_id: str, payload: Mapping[str, Any]
    ) -> str: ...


async def load_snapshot(db: Database, export_id: str) -> ExportSnapshotRef | None:
    def _read(conn) -> ExportSnapshotRef | None:
        row = conn.execute(
            "SELECT * FROM export_snapshots WHERE export_id = ?", (export_id,)
        ).fetchone()
        if row is None:
            return None
        return ExportSnapshotRef(
            export_id=row["export_id"],
            user_id=row["user_id"],
            historian_event_id=row["historian_event_id"],
            generated_at=datetime.fromisoformat(row["generated_at"]),
        )

    return await db.run(_read)


class ReimportService:
    """One reimport, end to end."""

    def __init__(
        self,
        db: Database,
        receipts: ReceiptRepository | None = None,
        history: HistorianQuery | None = None,
        flags: FlagSink | None = None,
    ) -> None:
        self._db = db
        self._receipts = receipts or ReceiptRepository(db)
        self._history = history or HistorianQuery(db)
        self._flags = flags

    async def submit(self, request: ReimportRequest) -> ReimportResult:
        if not request.content_scan_passed:
            # Fail closed. A scan that failed, timed out, or never ran all mean the same
            # thing here: unscanned, therefore unsafe. Never a silent bypass.
            return ReimportResult(
                ok=False,
                error_code=errors.UNSCANNED_FILE,
                error_detail="the file has not passed a Content Security scan",
            )

        parsed = parse_workbook(request.file_path)
        if not parsed.ok:
            return ReimportResult(
                ok=False, error_code=parsed.error_code, error_detail=parsed.error_detail
            )

        snapshot = await load_snapshot(self._db, parsed.snapshot_export_id)
        if snapshot is None:
            # Resolved policy (§9): a baseline that no longer exists is a rejection asking
            # for a fresh export, never an attempt to guess at or skip the missing base.
            return ReimportResult(
                ok=False,
                error_code=errors.STALE_SNAPSHOT_REFERENCE,
                error_detail=(
                    f"export {parsed.snapshot_export_id} is no longer on record; generate a "
                    "fresh export and reimport that instead"
                ),
            )

        actor = f"human:{request.actor_user_id}-via-reimport"
        applied_total = 0
        all_conflicts: list[FieldConflict] = []
        touched: list[str] = []

        for row in parsed.rows:
            outcome = await self._apply_row(row.receipt_id, row.values, snapshot, actor)
            if outcome is None:
                continue
            applied_count, conflicts, changed = outcome
            applied_total += applied_count
            all_conflicts.extend(conflicts)
            if changed:
                touched.append(row.receipt_id)

        flag_id = ""
        flag_error = ""
        if all_conflicts:
            flag_id, flag_error = await self._raise_conflict_flag(
                request.user_id, tuple(all_conflicts)
            )

        return ReimportResult(
            ok=True,
            fields_applied=applied_total,
            conflicts=tuple(all_conflicts),
            flag_id=flag_id,
            receipts_touched=tuple(touched),
            error_detail=flag_error,
        )

    async def _apply_row(
        self,
        receipt_id: str,
        reimported: Mapping[str, Any],
        snapshot: ExportSnapshotRef,
        actor: str,
    ):
        receipt = await self._receipts.get(receipt_id)
        if receipt is None:
            return None
        canonical = FrozenDict(receipt_to_row(receipt))
        # The baseline is reconstructed from the append-only trail as of the export's own
        # timestamp — no second copy of the data stored anywhere to drift from it.
        original = await self._history.state_as_of("receipts", receipt_id, snapshot.generated_at)
        if original is None:
            # The receipt has no history at or before the export — it was not in that file,
            # so there is no honest baseline for it. Skipped rather than diffed against
            # whatever happens to be current, which would silently apply every value.
            return None

        resolution = three_way_resolve(
            original, canonical, reimported, receipt_id=receipt_id
        )
        updates = {
            name: resolution.resolved[name]
            for name in resolution.applied_fields
        }
        if updates:
            await self._receipts.apply_field_updates(receipt_id, updates, actor=actor)
        return len(resolution.applied_fields), resolution.conflicts, bool(updates)

    async def _raise_conflict_flag(
        self, user_id: str, conflicts: tuple[FieldConflict, ...]
    ) -> tuple[str, str]:
        if self._flags is None:
            return "", (
                "conflicts were found but no Review/Flagging sink is configured — they are "
                "reported in this result and have NOT been surfaced for human review"
            )
        payload = {
            "conflict_count": len(conflicts),
            "receipt_ids": sorted({c.receipt_id for c in conflicts if c.receipt_id}),
            "fields": sorted({c.field for c in conflicts}),
        }
        flag_id = await self._flags.raise_flag(
            errors.CONFLICT_FLAG_TYPE, user_id, FrozenDict(payload)
        )
        return flag_id, ""


__all__ = ["FlagSink", "ReimportService", "load_snapshot"]

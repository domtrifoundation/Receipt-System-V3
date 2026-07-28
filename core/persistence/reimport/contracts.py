"""Reimport contracts (`v3-deepdive-30-reimport.md` §4, §7).

Types only. Reimport ingests a hand-edited exported workbook and reconciles it against
current canonical state; these are the shapes that crossing takes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from common.frozen_dict import FrozenDict


@dataclass(frozen=True)
class FieldConflict:
    """One field both the user and canonical state changed since the export, differently.

    Never resolved automatically. `canonical_value` stays authoritative in the meantime, but
    the conflict is surfaced as a `reimport_conflict` flag for a human — guessing wrong here
    is exactly the silent-data-loss failure `docs/PRINCIPLES.md` §4.3 rules out.
    """

    field: str
    original_value: Any
    canonical_value: Any
    reimported_value: Any
    receipt_id: str = ""


@dataclass(frozen=True)
class ParsedRow:
    """One receipt's worth of edited values read out of the workbook."""

    receipt_id: str
    values: FrozenDict


@dataclass(frozen=True)
class ParsedWorkbook:
    """A parsed reimport file, or the reason it could not be parsed.

    `snapshot_export_id` comes from the hidden reference cell the export writes. Without it
    there is no baseline to diff against, so a file missing it fails cleanly rather than
    being treated as a full-canonical overwrite (§8's own test).
    """

    ok: bool
    snapshot_export_id: str = ""
    rows: tuple[ParsedRow, ...] = ()
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class ReimportRequest:
    user_id: str
    file_path: str
    actor_user_id: str
    content_scan_passed: bool = False


@dataclass(frozen=True)
class ReimportResult:
    """Errors are data (`docs/PRINCIPLES.md` §4.1).

    `flag_id` is populated only when conflicts were found — it is the created
    `reimport_conflict` flag a human resolves through Review/Flagging.
    """

    ok: bool
    fields_applied: int = 0
    conflicts: tuple[FieldConflict, ...] = ()
    flag_id: str = ""
    receipts_touched: tuple[str, ...] = ()
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class ResolutionOutcome:
    """The result of one three-way resolution: what to write, and what to escalate."""

    resolved: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    conflicts: tuple[FieldConflict, ...] = ()
    applied_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class SnapshotBaseline:
    """The export snapshot a reimport diffs against, resolved from `export_snapshots`."""

    export_id: str
    historian_event_id: str
    generated_at: datetime
    values_by_receipt: FrozenDict


__all__ = [
    "FieldConflict",
    "ParsedRow",
    "ParsedWorkbook",
    "ReimportRequest",
    "ReimportResult",
    "ResolutionOutcome",
    "SnapshotBaseline",
]

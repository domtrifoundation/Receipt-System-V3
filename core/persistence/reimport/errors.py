"""Reimport error codes.

`MISSING_SNAPSHOT_REFERENCE` and `STALE_SNAPSHOT_REFERENCE` are separate codes on purpose:
one means the file was damaged (a user deleted the row or column holding the hidden
reference cell), the other means the baseline it names no longer exists. Both are rejections
rather than best-effort merges, and both ask the user for a fresh export — but they are
different problems and a caller should be able to say which one happened (§9 there).
"""

from __future__ import annotations

UNSCANNED_FILE = "reimport_unscanned_file"
UNREADABLE_FILE = "reimport_unreadable_file"
MISSING_SNAPSHOT_REFERENCE = "reimport_missing_snapshot_reference"
STALE_SNAPSHOT_REFERENCE = "reimport_stale_snapshot_reference"
PARSER_UNAVAILABLE = "reimport_parser_unavailable"
UNKNOWN_RECEIPT = "reimport_unknown_receipt"

#: The Review/Flagging flag type a genuine conflict raises. Named in file 01's taxonomy;
#: referenced here, never redefined — the taxonomy is Architect's, not this API's.
CONFLICT_FLAG_TYPE = "reimport_conflict"


class ReimportError(Exception):
    code = UNREADABLE_FILE


class MissingSnapshotReference(ReimportError):
    code = MISSING_SNAPSHOT_REFERENCE


class StaleSnapshotReference(ReimportError):
    """The referenced export record no longer exists — purged, or past retention.

    There is no valid baseline to diff against, so the reimport is rejected with an
    actionable message asking for a fresh export rather than guessing at or silently
    skipping the missing baseline.
    """

    code = STALE_SNAPSHOT_REFERENCE


class ParserUnavailable(ReimportError):
    """`openpyxl` is not installed. The capability degrades to unavailable (§4.4)."""

    code = PARSER_UNAVAILABLE


__all__ = [
    "CONFLICT_FLAG_TYPE",
    "MISSING_SNAPSHOT_REFERENCE",
    "PARSER_UNAVAILABLE",
    "STALE_SNAPSHOT_REFERENCE",
    "UNKNOWN_RECEIPT",
    "UNREADABLE_FILE",
    "UNSCANNED_FILE",
    "MissingSnapshotReference",
    "ParserUnavailable",
    "ReimportError",
    "StaleSnapshotReference",
]

"""Reads a hand-edited reimport workbook (`v3-deepdive-30-reimport.md` §3).

`openpyxl` is the library, deliberately the same one `exports/providers/excel_general.py`
writes with — round-tripping one file format asymmetrically (write with A, read with B) is
how subtle format drift gets introduced between the two halves of a round trip.

**This is the only module in this repository that imports `openpyxl` for reading**, and the
import is lazy: a missing `openpyxl` degrades reimport to unavailable rather than failing
process startup for every install that never reimports anything (`docs/PRINCIPLES.md` §3.3
point 5, §4.4).

**The hidden snapshot-reference cell is what makes the three-way diff possible at all.**
Without it there is no way to tell "the user changed this field" apart from "this field
happens to differ from current canonical state." A file whose reference cell was stripped —
a user deleting the row or column that happened to hold it — fails cleanly with an
actionable error, never a silent full-canonical overwrite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.frozen_dict import FrozenDict

from . import errors
from .contracts import ParsedRow, ParsedWorkbook

#: Where the export writes its baseline reference. Kept next to the parser that reads it so
#: the writing and reading halves cannot drift to different cells silently.
SNAPSHOT_SHEET = "_resibo_meta"
SNAPSHOT_CELL = "A1"
SNAPSHOT_PREFIX = "resibo-export:"

#: The raw-data sheet the summary sheet's live formulas pull from. The user edits here.
DATA_SHEET = "Receipts"
RECEIPT_ID_COLUMN = "receipt_id"


def openpyxl_available() -> bool:
    """Feature detection, not a version check — the capability either resolves or it does
    not, and the answer is the same shape on every interpreter."""
    try:
        import openpyxl  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def parse_workbook(path: Path | str) -> ParsedWorkbook:
    """Read one reimported workbook into rows plus its snapshot reference.

    Errors are data here too — this returns a `ParsedWorkbook` with a code rather than
    raising, so the caller's own result assembly stays a straight line.
    """
    try:
        from openpyxl import load_workbook  # noqa: PLC0415
    except ImportError as exc:
        return ParsedWorkbook(
            ok=False,
            error_code=errors.PARSER_UNAVAILABLE,
            error_detail=f"openpyxl is not installed ({exc})",
        )

    file_path = Path(path)
    if not file_path.exists():
        return ParsedWorkbook(
            ok=False, error_code=errors.UNREADABLE_FILE, error_detail=str(file_path)
        )
    try:
        # `data_only=True` reads the cached values of the summary sheet's live formulas
        # rather than the formula strings themselves — a reimport wants the numbers a user
        # saw and edited, not `=Receipts!C4`.
        workbook = load_workbook(filename=str(file_path), data_only=True)
    except Exception as exc:  # noqa: BLE001 - any malformed workbook is one error to caller
        return ParsedWorkbook(
            ok=False, error_code=errors.UNREADABLE_FILE, error_detail=str(exc)
        )

    export_id = _read_snapshot_reference(workbook)
    if not export_id:
        return ParsedWorkbook(
            ok=False,
            error_code=errors.MISSING_SNAPSHOT_REFERENCE,
            error_detail=(
                "the hidden export-reference cell is missing or corrupted; a fresh export "
                "is needed before this file can be reimported"
            ),
        )

    if DATA_SHEET not in workbook.sheetnames:
        return ParsedWorkbook(
            ok=False,
            error_code=errors.UNREADABLE_FILE,
            error_detail=f"no '{DATA_SHEET}' sheet in the workbook",
        )

    rows = tuple(_read_rows(workbook[DATA_SHEET]))
    return ParsedWorkbook(ok=True, snapshot_export_id=export_id, rows=rows)


def _read_snapshot_reference(workbook: Any) -> str:
    if SNAPSHOT_SHEET not in workbook.sheetnames:
        return ""
    raw = workbook[SNAPSHOT_SHEET][SNAPSHOT_CELL].value
    if not isinstance(raw, str) or not raw.startswith(SNAPSHOT_PREFIX):
        return ""
    return raw[len(SNAPSHOT_PREFIX) :].strip()


def _read_rows(sheet: Any):
    rows = sheet.iter_rows(values_only=True)
    try:
        header = next(rows)
    except StopIteration:
        return
    columns = [str(h) if h is not None else "" for h in header]
    if RECEIPT_ID_COLUMN not in columns:
        return
    id_index = columns.index(RECEIPT_ID_COLUMN)
    for row in rows:
        receipt_id = row[id_index]
        if not receipt_id:
            continue
        values = {
            column: row[i]
            for i, column in enumerate(columns)
            if column and column != RECEIPT_ID_COLUMN and i < len(row)
        }
        yield ParsedRow(receipt_id=str(receipt_id), values=FrozenDict(values))


__all__ = [
    "DATA_SHEET",
    "RECEIPT_ID_COLUMN",
    "SNAPSHOT_CELL",
    "SNAPSHOT_PREFIX",
    "SNAPSHOT_SHEET",
    "openpyxl_available",
    "parse_workbook",
]

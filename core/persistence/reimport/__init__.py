"""Reimport — ingesting a hand-edited export and reconciling it against canonical state.

Import types from `.contracts`. `three_way_resolve` is a pure function on purpose; the
orchestration that scans, parses, writes and flags lives in `conflict_resolution.py`.
"""

from .contracts import (
    FieldConflict,
    ParsedRow,
    ParsedWorkbook,
    ReimportRequest,
    ReimportResult,
    ResolutionOutcome,
)
from .conflict_resolution import FlagSink, ReimportService
from .three_way_diff import three_way_resolve

__all__ = [
    "FieldConflict",
    "FlagSink",
    "ParsedRow",
    "ParsedWorkbook",
    "ReimportRequest",
    "ReimportResult",
    "ReimportService",
    "ResolutionOutcome",
    "three_way_resolve",
]

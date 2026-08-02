"""Historian — Persistence's append-only, two-track history sub-package.

Import types from `.contracts`. `HistorianWriter` deliberately exposes no update or delete
method anywhere; that absence is the append-only guarantee (`docs/PRINCIPLES.md` §2.3).
"""

from .contracts import (
    DataChange,
    HistorianEvent,
    HistoryEntry,
    NarrativeEvent,
    NarrativeStage,
)
from .query import HistorianQuery
from .writer import HistorianWriter

__all__ = [
    "DataChange",
    "HistorianEvent",
    "HistorianQuery",
    "HistorianWriter",
    "HistoryEntry",
    "NarrativeEvent",
    "NarrativeStage",
]

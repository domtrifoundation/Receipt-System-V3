"""Historian contracts — both tracks (`v3-deepdive-29-historian.md` §4).

Types only. Historian owns two structurally distinct, both append-only tracks living in the
same database and queryable together as one chronological per-receipt history:

- **The data-change track** (`HistorianEvent`) — table/row/before/after for every logical
  write to canonical data, atomic with the write itself.
- **The narrative track** (`NarrativeEvent`) — a quantized, human-readable account of every
  pipeline stage a receipt passed through.

**The hard rule this file's `detail` field exists under**: the narrative track is quantized
by design and is *webapp-displayable*, unlike Logs which is origin-server-only. "Tesseract
read this receipt at 87% confidence" belongs here; the raw OCR text, the full LLM
prompt/response, and detailed timing belong to Logs. Letting `detail` creep toward Logs'
verbosity both bloats the canonical database and starts leaking server-internal detail to a
remote audience (§1 there).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from common.frozen_dict import FrozenDict


class NarrativeStage(str, Enum):
    """One entry per pipeline stage, plus the two lifecycle markers.

    `OCR_ENGINE_RESULT` is deliberately per-engine-reading rather than per-stage: the
    user-facing point of this track is seeing that engine X read at one confidence and
    engine Y at another, which a single merged entry would erase.
    """

    RUN_STARTED = "run_started"
    INGESTED = "ingested"
    PREPROCESSED = "preprocessed"
    OCR_ENGINE_RESULT = "ocr_engine_result"
    OCR_CORROBORATED = "ocr_corroborated"
    MATCHED = "matched"
    GEOD = "geod"
    INFERENCE_DELIBERATED = "inference_deliberated"
    FLAGGED = "flagged"
    WRITTEN = "written"
    RESCAN_STARTED = "rescan_started"


@dataclass(frozen=True)
class HistorianEvent:
    """The data-change track. `before` is None for an INSERT, `after` None for a DELETE."""

    event_id: str
    table_name: str
    row_id: str
    before: FrozenDict | None
    after: FrozenDict | None
    actor: str
    program_version: str
    occurred_at: datetime


@dataclass(frozen=True)
class NarrativeEvent:
    """The narrative track. `detail` is quantized — see the module docstring's hard rule."""

    event_id: str
    receipt_id: str
    run_id: str
    stage: NarrativeStage
    summary: str
    occurred_at: datetime
    triggered_by: str = "initial_scan"
    detail: FrozenDict = field(default_factory=lambda: FrozenDict({}))


#: A receipt's history is both tracks interleaved. Named here so `query.py` and the service
#: layer agree on one type rather than each writing their own union inline.
HistoryEntry = HistorianEvent | NarrativeEvent


@dataclass(frozen=True)
class DataChange:
    """One pending canonical change, handed to `write_with_history` together with its rows.

    This type is what makes the same-transaction guarantee expressible: a caller cannot ask
    for the data write without also supplying the event, because they are one argument.
    """

    table_name: str
    row_id: str
    before: FrozenDict | None
    after: FrozenDict | None
    actor: str


__all__ = [
    "DataChange",
    "HistorianEvent",
    "HistoryEntry",
    "NarrativeEvent",
    "NarrativeStage",
]

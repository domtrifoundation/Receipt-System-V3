"""Historian error codes.

Historian shares Persistence's boundary discipline: codes are data, never raised across
gRPC. `MUTATION_ATTEMPTED` exists because the database-level append-only triggers can fire,
and when they do the caller deserves a code that names what actually happened rather than a
generic transaction failure.
"""

from __future__ import annotations

HISTORY_NOT_FOUND = "history_not_found"
MUTATION_ATTEMPTED = "historian_mutation_attempted"
NARRATIVE_VERBOSITY_REJECTED = "narrative_verbosity_rejected"


class HistorianError(Exception):
    """Internal only. Never crosses a boundary."""

    code = MUTATION_ATTEMPTED


class NarrativeVerbosityRejected(HistorianError):
    """A summarizer tried to put Logs-resolution content into `NarrativeEvent.detail`.

    Raised internally by `narrative/summarizers.py`'s own guard, which is the enforcement
    half of §1's "quantized, never Logs-resolution" rule — a documented intention alone is
    what lets this drift.
    """

    code = NARRATIVE_VERBOSITY_REJECTED


__all__ = [
    "HISTORY_NOT_FOUND",
    "MUTATION_ATTEMPTED",
    "NARRATIVE_VERBOSITY_REJECTED",
    "HistorianError",
    "NarrativeVerbosityRejected",
]

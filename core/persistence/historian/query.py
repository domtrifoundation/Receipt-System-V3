"""Interleaved, chronological history across both tracks (`v3-deepdive-29-historian.md` §6).

A receipt's full story in one timeline: the run starting, each OCR engine's own reading,
corroboration, matching, geocoding, the LLM's deliberation, the final write — interspersed
with any later data-change events from a human correction, and with a subsequent
`RESCAN_STARTED` sequence sitting alongside the original rather than replacing it.

Read-only by construction: nothing in this module writes, and it holds no connection of its
own beyond what `Database.run` hands it for the duration of one call.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from common.frozen_dict import FrozenDict

from ..db.connection import Database
from .contracts import HistorianEvent, HistoryEntry, NarrativeEvent, NarrativeStage
from .writer import loads_payload


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_historian(row: sqlite3.Row) -> HistorianEvent:
    return HistorianEvent(
        event_id=row["event_id"],
        table_name=row["table_name"],
        row_id=row["row_id"],
        before=loads_payload(row["before_json"]),
        after=loads_payload(row["after_json"]),
        actor=row["actor"],
        program_version=row["program_version"],
        occurred_at=_dt(row["occurred_at"]),
    )


def _row_to_narrative(row: sqlite3.Row) -> NarrativeEvent:
    return NarrativeEvent(
        event_id=row["event_id"],
        receipt_id=row["receipt_id"],
        run_id=row["run_id"],
        stage=NarrativeStage(row["stage"]),
        summary=row["summary"],
        detail=loads_payload(row["detail_json"]),  # type: ignore[arg-type]
        triggered_by=row["triggered_by"],
        occurred_at=_dt(row["occurred_at"]),
    )


class HistorianQuery:
    """The read side of both tracks."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_receipt_history(self, receipt_id: str) -> tuple[HistoryEntry, ...]:
        """Both tracks, merged and sorted by `occurred_at`.

        The data-change track is keyed by `row_id`, the narrative track by `receipt_id` —
        for a receipt row those are the same value, which is what makes one merged feed
        possible without a join table.
        """

        def _read(conn: sqlite3.Connection) -> tuple[HistoryEntry, ...]:
            changes = conn.execute(
                "SELECT * FROM historian_events WHERE row_id = ? ORDER BY occurred_at",
                (receipt_id,),
            ).fetchall()
            narrative = conn.execute(
                "SELECT * FROM narrative_events WHERE receipt_id = ? ORDER BY occurred_at",
                (receipt_id,),
            ).fetchall()
            entries: list[HistoryEntry] = [_row_to_historian(r) for r in changes]
            entries += [_row_to_narrative(r) for r in narrative]
            # Sorted on occurred_at alone, with event_id as a stable tiebreak so two events
            # recorded in the same microsecond do not reorder between identical queries.
            entries.sort(key=lambda e: (e.occurred_at, e.event_id))
            return tuple(entries)

        return await self._db.run(_read)

    async def get_row_changes(
        self, table_name: str, row_id: str
    ) -> tuple[HistorianEvent, ...]:
        """The data-change track alone, for a row that is not a receipt."""

        def _read(conn: sqlite3.Connection) -> tuple[HistorianEvent, ...]:
            rows = conn.execute(
                "SELECT * FROM historian_events WHERE table_name = ? AND row_id = ?"
                " ORDER BY occurred_at",
                (table_name, row_id),
            ).fetchall()
            return tuple(_row_to_historian(r) for r in rows)

        return await self._db.run(_read)

    async def get_event(self, event_id: str) -> HistorianEvent | None:
        """One data-change event by id — what Reimport resolves its snapshot baseline
        against, and what makes a stale snapshot reference detectable rather than guessed
        at (`v3-deepdive-30-reimport.md` §9)."""

        def _read(conn: sqlite3.Connection) -> HistorianEvent | None:
            row = conn.execute(
                "SELECT * FROM historian_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            return _row_to_historian(row) if row else None

        return await self._db.run(_read)

    async def latest_event_id(self) -> str:
        """The newest data-change event id, stamped into an export as its baseline."""

        def _read(conn: sqlite3.Connection) -> str:
            row = conn.execute(
                "SELECT event_id FROM historian_events ORDER BY occurred_at DESC LIMIT 1"
            ).fetchone()
            return row["event_id"] if row else ""

        return await self._db.run(_read)

    async def state_as_of(
        self, table_name: str, row_id: str, as_of: datetime
    ) -> FrozenDict | None:
        """A row's canonical state at a past instant, reconstructed from the append-only
        trail rather than stored a second time.

        This is what gives Reimport its three-way *base* without an extra snapshot table:
        the newest data-change event at or before `as_of` carries that row's `after` image,
        which is exactly what the export contained. It only works because the track is
        genuinely append-only — a mutable history could not answer this question honestly,
        which is a concrete payoff of §2.3 rather than a restatement of it.

        Returns `None` when the row has no event that old, meaning it was not in that
        export at all.
        """

        def _read(conn: sqlite3.Connection) -> FrozenDict | None:
            row = conn.execute(
                "SELECT after_json FROM historian_events WHERE table_name = ? AND row_id = ?"
                " AND occurred_at <= ? ORDER BY occurred_at DESC LIMIT 1",
                (table_name, row_id, as_of.isoformat()),
            ).fetchone()
            return loads_payload(row["after_json"]) if row else None

        return await self._db.run(_read)

    async def narrative_for_run(
        self, receipt_id: str, run_id: str
    ) -> tuple[NarrativeEvent, ...]:
        """One run's own narrative sequence. A rescan is a different `run_id`, which is what
        lets the original scan's narrative and every later one coexist untouched (§7)."""

        def _read(conn: sqlite3.Connection) -> tuple[NarrativeEvent, ...]:
            rows = conn.execute(
                "SELECT * FROM narrative_events WHERE receipt_id = ? AND run_id = ?"
                " ORDER BY occurred_at",
                (receipt_id, run_id),
            ).fetchall()
            return tuple(_row_to_narrative(r) for r in rows)

        return await self._db.run(_read)


__all__ = ["HistorianQuery"]

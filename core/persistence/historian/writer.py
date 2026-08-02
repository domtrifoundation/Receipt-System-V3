"""Append-only event insertion for both tracks (`v3-deepdive-29-historian.md` §9).

**Append-only is a structural property of this module's public surface, not a policy.**
There is no `update_event`, no `delete_event`, no `amend`, and no method that hands out the
connection. That absence is the guarantee: an audit trail's entire value is being
trustworthy evidence in exactly the scenario where someone would want to quietly alter it
(`docs/PRINCIPLES.md` §2.3). The database-level triggers in `db/schema.py` are the backstop
for a raw statement that bypasses this module entirely. If you are adding a mutation method
here, that is the bug — not a missing feature.

**Why Historian is a sub-package of Persistence rather than a peer API.** `write_with_history`
commits the canonical data write and its event in *one* SQL transaction. Two separate
services could not give that guarantee at all; one process sharing one connection can. That
atomicity is the entire architectural reason for this package's placement (§5 of the parent
deep-dive), so anything that would split the two writes across transactions undoes the
reason this code lives here.

**The narrative track is deliberately held to a looser bar** (§9 there). It is written by
Execution Core's checkpoint wrapper, not inline with a canonical write, so a narrative event
is atomic with its own checkpoint but not with the eventual final write. Worst case that
costs one missing narrative line on a receipt that gets retried anyway — a far smaller
consequence than a canonical write landing without its audit record, which is what the hard
guarantee above actually exists to prevent.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from common.frozen_dict import FrozenDict
from common.version import PROGRAM_VERSION

from ..contracts import utcnow
from ..db.connection import Database
from .contracts import DataChange, HistorianEvent, NarrativeEvent

T = TypeVar("T")


def dumps_payload(payload: Mapping[str, Any] | None) -> str | None:
    """Serialize a `FrozenDict`-or-`Mapping` payload.

    Typed as `Mapping`, checked as `Mapping`, never as `dict`: Python 3.15's builtin
    `frozendict` inherits from `object`, so `isinstance(x, dict)` silently returns False for
    it and the wrong branch gets taken (`docs/PRINCIPLES.md` §2.1).
    """
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise TypeError(f"expected a Mapping payload, got {type(payload)!r}")
    return json.dumps(dict(payload), default=str, sort_keys=True)


def loads_payload(value: str | None) -> FrozenDict | None:
    return None if value is None else FrozenDict(json.loads(value))


class HistorianWriter:
    """Both tracks' write surface. Append-only by construction — see the module docstring."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # --------------------------------------------------- the atomic guarantee
    def append_data_change_sync(
        self, conn: sqlite3.Connection, change: DataChange
    ) -> HistorianEvent:
        """Insert one data-change event on an *already-open* transaction.

        Takes the connection rather than opening its own, precisely so the caller's data
        write and this event share one transaction. Not part of the public API surface —
        `write_with_history` below is.
        """
        event = HistorianEvent(
            event_id=uuid.uuid4().hex,
            table_name=change.table_name,
            row_id=change.row_id,
            before=change.before,
            after=change.after,
            actor=change.actor,
            program_version=PROGRAM_VERSION,
            occurred_at=utcnow(),
        )
        conn.execute(
            "INSERT INTO historian_events (event_id, table_name, row_id, before_json,"
            " after_json, actor, program_version, occurred_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                event.event_id,
                event.table_name,
                event.row_id,
                dumps_payload(event.before),
                dumps_payload(event.after),
                event.actor,
                event.program_version,
                event.occurred_at.isoformat(),
            ),
        )
        return event

    async def write_with_history(
        self,
        change: DataChange,
        apply: Callable[[sqlite3.Connection], T],
    ) -> tuple[T, HistorianEvent]:
        """Apply a canonical data write and record its event in ONE transaction.

        Either both land or neither does. If `apply` raises, the whole transaction rolls
        back and no event survives; if the event insert fails, the data write rolls back
        with it. This is the concrete mechanism behind §5's guarantee and the thing the
        dual-write atomicity test actually validates.
        """

        def _txn(conn: sqlite3.Connection) -> tuple[T, HistorianEvent]:
            applied = apply(conn)
            event = self.append_data_change_sync(conn, change)
            return applied, event

        return await self._db.transaction(_txn)

    # ------------------------------------------------------- narrative track
    def append_narrative_sync(
        self, conn: sqlite3.Connection, event: NarrativeEvent
    ) -> NarrativeEvent:
        conn.execute(
            "INSERT INTO narrative_events (event_id, receipt_id, run_id, stage, summary,"
            " detail_json, triggered_by, occurred_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                event.event_id,
                event.receipt_id,
                event.run_id,
                event.stage.value,
                event.summary,
                dumps_payload(event.detail) or "{}",
                event.triggered_by,
                event.occurred_at.isoformat(),
            ),
        )
        return event

    async def append_narrative(self, event: NarrativeEvent) -> NarrativeEvent:
        """One narrative event. Looser atomicity than the data-change track, by design."""
        return await self._db.transaction(
            lambda conn: self.append_narrative_sync(conn, event)
        )

    async def append_narrative_batch(
        self, events: tuple[NarrativeEvent, ...]
    ) -> tuple[NarrativeEvent, ...]:
        """One stage can produce several events — OCR emits one per engine reading plus one
        for the corroborated outcome. They go in together so a partially-written stage is
        not a state the timeline can be read in."""

        def _txn(conn: sqlite3.Connection) -> tuple[NarrativeEvent, ...]:
            for event in events:
                self.append_narrative_sync(conn, event)
            return events

        return await self._db.transaction(_txn)


__all__ = ["HistorianWriter", "dumps_payload", "loads_payload"]

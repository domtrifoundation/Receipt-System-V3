"""Audit sink providers and the registry that fans a write out across all of them.

`contracts.AuditSink` is the Protocol; this file holds the one sink that always exists
(`SqliteAuditSink`, backed by Audit's own top-level database per §3.1) and the registry
`writer.py` writes through.

**Why a registry rather than a single hard-coded store** (`docs/PRINCIPLES.md` §1.2): a
privileged-action trail is one of the few things in this system where a second,
independently-controlled copy is a real requirement rather than a nice-to-have — an
installation whose compliance posture calls for a WORM volume or an off-box appliance holding
its own copy registers that as a mirror *alongside* the SQLite primary. That is running
several providers simultaneously for real value, which is §1.2's own test for this shape,
rather than one backend selected from config and swapped.

The asymmetry between primary and mirror is the whole design and is deliberate:
- the **primary** failing is an error the caller must see, because a caller that believes it
  recorded an audit entry when it did not is precisely the failure this API cannot have;
- a **mirror** failing degrades — it is named in `RecordResult.degraded_sinks` and the write
  still succeeds, because losing a redundant copy is not a reason to fail the privileged
  action that was already performed (`docs/PRINCIPLES.md` §4.4).

Note that no type in this file has an update or delete method, and the registry never hands
out its sinks' connections. Append-only is the shape of the surface, not a policy (§3.2).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .contracts import AuditEvent, AuditSink
from .db import INSERT_SQL, connect, database_bytes, event_to_row
from .errors import AppendOnlyViolation, SinkUnavailable


class SqliteAuditSink:
    """The mandatory primary sink: Audit's own small top-level SQLite database (§3.1).

    Its connection is opened under the `append` authorizer profile, so `UPDATE` and `DELETE`
    are refused by SQLite itself before execution — not merely absent from this class.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = connect(db_path, profile="append")

    @property
    def name(self) -> str:
        return "sqlite"

    @property
    def is_primary(self) -> bool:
        return True

    def append(self, event: AuditEvent) -> None:
        try:
            with self._lock:
                self._conn.execute(INSERT_SQL, event_to_row(event))
                self._conn.commit()
        except sqlite3.IntegrityError as exc:
            # A duplicate event_id. Genuinely a caller bug, but worth distinguishing from an
            # unreachable database: retrying it forever would never succeed.
            raise SinkUnavailable(f"audit event rejected: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            if "not authorized" in str(exc):
                raise AppendOnlyViolation(str(exc)) from exc
            raise SinkUnavailable(str(exc)) from exc

    # Read helpers used by `query.py`/`metrics.py` are deliberately NOT here — this sink's
    # own surface is append and close, nothing more. Reads open their own connection under
    # the `read` profile, which cannot write at all.

    def size_bytes(self) -> int:
        return database_bytes(self._conn, self._path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class SinkRegistry:
    """Holds the enabled sinks. Genuinely mutable internal state, so a plain list, not a
    frozen collection — `docs/PRINCIPLES.md` §2.1.1 draws that line at intent, and a
    registry populated at startup is the example it names as correctly mutable."""

    def __init__(self, primary: AuditSink | None = None) -> None:
        self._sinks: list[AuditSink] = []
        if primary is not None:
            self.register(primary)

    def register(self, sink: AuditSink) -> None:
        if sink.is_primary and any(s.is_primary for s in self._sinks):
            raise ValueError("exactly one primary sink is permitted")
        if any(s.name == sink.name for s in self._sinks):
            raise ValueError(f"a sink named {sink.name!r} is already registered")
        self._sinks.append(sink)

    @property
    def primary(self) -> AuditSink | None:
        return next((s for s in self._sinks if s.is_primary), None)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self._sinks)

    def fan_out(self, event: AuditEvent) -> tuple[str, ...]:
        """Write to every registered sink. Returns the names of mirrors that degraded.

        The primary is written first and its failure propagates; mirrors are attempted
        regardless of each other, so one broken mirror never suppresses a working one.
        """
        primary = self.primary
        if primary is None:
            raise SinkUnavailable("no primary audit sink is registered")
        primary.append(event)  # raises; the caller turns it into result data

        degraded: list[str] = []
        for sink in self._sinks:
            if sink.is_primary:
                continue
            try:
                sink.append(event)
            except Exception:  # noqa: BLE001 - a mirror must never take a write down
                # The bare name, not "name: message". `RecordResult.degraded_sinks` is
                # documented as sink *names*, and a caller comparing an entry against a
                # registered sink's `name` would never match a message-appended string.
                degraded.append(sink.name)
        return tuple(degraded)

    def close(self) -> None:
        for sink in self._sinks:
            try:
                sink.close()
            except Exception:  # noqa: BLE001 - closing a broken mirror is not an error
                pass
        self._sinks.clear()


__all__ = ["SinkRegistry", "SqliteAuditSink"]

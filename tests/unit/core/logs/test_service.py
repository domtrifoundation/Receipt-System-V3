"""gRPC surface tests (§7).

The servicer is a thin translation layer over `query.py` on purpose, so these tests check
translation and the streamed-error shape — not the read semantics, which belong to
`test_query.py` and must not be asserted twice in two places that could drift.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.logs.contracts import LogEntry, LogLevel, LogQuery
from core.logs.index import LogIndex
from core.logs.query import AuthBreakGlassChecker, LogReader
from core.logs.service import LogsServicer, to_query, to_record
from core.logs.sinks import JsonlFileSink, SinkRegistry
from core.logs.writer import LogWriter

pb = pytest.importorskip(
    "core.logs.generated.logs_pb2",
    reason="generated stubs absent; regenerate with grpc_tools.protoc (see CLAUDE.md)",
)

BASE = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)


def _reader(tmp_path, checker=None) -> LogReader:
    index = LogIndex(tmp_path / "index.sqlite", root=tmp_path)
    registry = SinkRegistry()
    registry.register(JsonlFileSink(tmp_path))
    writer = LogWriter(tmp_path, registry=registry, index=index)
    for i, level in enumerate([LogLevel.INFO, LogLevel.ATTENTION]):
        writer.write_sync(
            LogEntry(BASE + timedelta(minutes=i), "run-a", "user-1", "ocr", level, f"e{i}")
        )
    writer.close()
    return LogReader(tmp_path, index=index, checker=checker)


def test_request_translation_treats_empty_strings_as_unset():
    """proto3 has no null; an omitted field arrives as "" and must not become a filter that
    matches nothing."""
    query = to_query(pb.LogQueryRequest(run_id="run-a", requesting_user_id="user-1"))
    assert query == LogQuery(
        run_id="run-a", requesting_user_id="user-1", min_level=LogLevel.INFO, limit=1000
    )


def test_unknown_level_defers_to_info_rather_than_failing():
    """A client built against a future version that added a level gets a usable stream, not
    a rejection (§4.4)."""
    assert to_query(pb.LogQueryRequest(min_level="chatty")).min_level is LogLevel.INFO


def test_record_carries_the_style_hint_so_a_client_needs_no_table_of_its_own():
    """§3.4: the hint is published with the entry precisely so no client maintains a second,
    drifting opinion about severity. It is a hint, not a Rich markup string — Logs renders
    nothing and does not know Interface exists."""
    from common.frozen_dict import FrozenDict

    record = to_record(
        LogEntry(BASE, "run-a", "user-1", "ocr", LogLevel.ATTENTION, "drifted",
                 context=FrozenDict({"engine": "paddle"})),
        pb,
    )
    assert record.entry.suggested_style == "critical_persistent"
    assert record.entry.level == "attention"
    assert '"engine": "paddle"' in record.entry.context_json


def test_traceback_survives_the_wire_translation():
    record = to_record(
        LogEntry(BASE, None, None, "ocr", LogLevel.ERROR, "failed",
                 traceback="Traceback (most recent call last):\n  boom"),
        pb,
    )
    assert record.entry.traceback.startswith("Traceback (most recent call last):")
    assert record.entry.run_id == ""  # absent, not the string "None"


def test_a_time_bound_with_no_offset_arrives_timezone_aware():
    """`fromisoformat` accepts an offsetless RFC-3339-ish value happily and returns a naive
    datetime; the read path compares it against aware entry timestamps. Normalised to UTC
    at translation so a client cannot turn a bound into a `TypeError` at the boundary."""
    query = to_query(pb.LogQueryRequest(since="2026-07-01", until="2026-07-31T00:00:00"))
    assert query.since.tzinfo is not None and query.until.tzinfo is not None
    assert query.since.utcoffset().total_seconds() == 0


def test_query_streams_entries(tmp_path):
    servicer = LogsServicer(_reader(tmp_path))
    request = pb.LogQueryRequest(
        run_id="run-a", user_id="user-1", requesting_user_id="user-1", min_level="trace"
    )
    records = list(servicer.Query(request, context=None))
    assert [r.entry.message for r in records] == ["e0", "e1"]
    assert all(r.error.error_code == "" for r in records)


def test_a_denied_read_is_a_terminal_error_frame_not_a_grpc_status(tmp_path):
    """Errors are data at this boundary (`docs/PRINCIPLES.md` §4.1): the client gets a reason
    it can show rather than an exception it has to catch."""
    servicer = LogsServicer(_reader(tmp_path))
    records = list(
        servicer.Query(
            pb.LogQueryRequest(user_id="user-2", requesting_user_id="user-1"), context=None
        )
    )
    assert len(records) == 1
    assert records[0].error.error_code == "CROSS_USER_ACCESS_DENIED"
    assert records[0].error.error_detail


def test_break_glass_path_reaches_the_servicer(tmp_path):
    reader = _reader(tmp_path, checker=AuthBreakGlassChecker(lambda req, sub: req == "staff"))
    records = list(
        LogsServicer(reader).Query(
            pb.LogQueryRequest(user_id="user-1", requesting_user_id="staff", min_level="trace"),
            context=None,
        )
    )
    assert [r.entry.message for r in records] == ["e0", "e1"]

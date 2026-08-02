"""Retention tests (§5, §10)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from core.logs.contracts import LogEntry, LogLevel, RetentionPolicy
from core.logs.index import LogIndex
from core.logs.metrics import LogsMetricsCollector
from core.logs.retention import expired_files, purge
from core.logs.sinks import JsonlFileSink, SinkRegistry
from core.logs.writer import LogWriter

TODAY = date(2026, 7, 17)


def _write_on(tmp_path, day: date, level: LogLevel, index: LogIndex | None = None) -> str:
    registry = SinkRegistry()
    registry.register(JsonlFileSink(tmp_path))
    from common.frozen_dict import FrozenDict
    from core.logs.contracts import Verbosity

    writer = LogWriter(
        tmp_path,
        verbosity=Verbosity(default=LogLevel.TRACE, per_service=FrozenDict({})),
        registry=registry,
        index=index,
    )
    when = datetime(day.year, day.month, day.day, 8, 0, tzinfo=timezone.utc)
    receipt = writer.write_sync(LogEntry(when, "run-1", "user-1", "ocr", level, "entry"))
    writer.close()
    return receipt.path


def test_trace_expires_on_its_own_shorter_window(tmp_path):
    """§10: 7 days for TRACE, 90 for everything else. Both files here are 30 days old and
    only one of them is past its window."""
    old = TODAY - timedelta(days=30)
    _write_on(tmp_path, old, LogLevel.TRACE)
    _write_on(tmp_path, old, LogLevel.INFO)
    doomed = expired_files(tmp_path, RetentionPolicy(), today=TODAY)
    assert [p.name.endswith(".trace.jsonl") for p in doomed] == [True]


def test_ordinary_trace_expires_at_ninety_days(tmp_path):
    _write_on(tmp_path, TODAY - timedelta(days=89), LogLevel.INFO)
    _write_on(tmp_path, TODAY - timedelta(days=120), LogLevel.INFO)
    doomed = expired_files(tmp_path, RetentionPolicy(), today=TODAY)
    assert len(doomed) == 1
    assert "2026-03-19" in doomed[0].name  # 120 days before 2026-07-17


def test_todays_file_is_never_swept(tmp_path):
    """A sweep that could delete the file a running service holds open would make retention
    able to break logging — the one thing this API must not do."""
    _write_on(tmp_path, TODAY, LogLevel.TRACE)
    assert expired_files(tmp_path, RetentionPolicy(trace_retention_days=0), today=TODAY) == ()


def test_purge_deletes_files_and_prunes_the_index_rows_that_pointed_at_them(tmp_path):
    index = LogIndex(tmp_path / "index.sqlite", root=tmp_path)
    stale = _write_on(tmp_path, TODAY - timedelta(days=200), LogLevel.INFO, index)
    fresh = _write_on(tmp_path, TODAY, LogLevel.INFO, index)
    metrics = LogsMetricsCollector()

    result = purge(tmp_path, index=index, metrics=metrics, today=TODAY)

    assert result.ok
    assert result.files_deleted == (stale,)
    assert result.index_rows_pruned == 1
    assert index.count() == 1  # the fresh entry's row survives
    assert metrics.snapshot().files_purged == 1
    from pathlib import Path

    assert not Path(stale).exists() and Path(fresh).exists()
    index.close()


def test_purge_on_an_empty_root_is_a_clean_no_op(tmp_path):
    result = purge(tmp_path, today=TODAY)
    assert result.ok and result.files_deleted == ()

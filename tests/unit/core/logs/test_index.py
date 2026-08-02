"""Index tests (§3.2).

The rebuild test is the deep-dive's own second named testing hook, and it is what keeps the
design claim honest: the index is a query accelerator over the JSONL files, never a second
source of truth. If it ever stopped being fully regenerable from the files alone, this test
is the one that should fail.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.logs.contracts import LogEntry, LogLevel, LogQuery
from core.logs.index import LogIndex
from core.logs.sinks import JsonlFileSink, SinkRegistry
from core.logs.writer import LogWriter

BASE = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)


def _writer_with_index(tmp_path) -> tuple[LogWriter, LogIndex]:
    index = LogIndex(tmp_path / "index.sqlite", root=tmp_path)
    registry = SinkRegistry()
    registry.register(JsonlFileSink(tmp_path))
    return LogWriter(tmp_path, registry=registry, index=index), index


def _populate(writer: LogWriter) -> None:
    for i, (service, level, run_id, user_id) in enumerate(
        [
            ("ocr", LogLevel.INFO, "run-a", "user-1"),
            ("ocr", LogLevel.ERROR, "run-a", "user-1"),
            ("inference", LogLevel.INFO, "run-b", "user-2"),
            ("ocr", LogLevel.WARNING, "run-b", "user-2"),
        ]
    ):
        writer.write_sync(
            LogEntry(
                BASE + timedelta(minutes=i), run_id, user_id, service, level, f"entry-{i}"
            )
        )


def test_locate_narrows_by_run_and_level(tmp_path):
    writer, index = _writer_with_index(tmp_path)
    _populate(writer)
    located = index.locate(LogQuery(run_id="run-a", min_level=LogLevel.INFO))
    assert len(located) == 2
    errors_only = index.locate(LogQuery(run_id="run-a", min_level=LogLevel.ERROR))
    assert len(errors_only) == 1
    writer.close()


def test_index_stores_locations_not_log_content(tmp_path):
    """The structural half of "not a second source of truth": nothing readable as log text
    lives in the database file."""
    writer, index = _writer_with_index(tmp_path)
    _populate(writer)
    blob = (tmp_path / "index.sqlite").read_bytes()
    assert b"entry-0" not in blob
    assert index.count() == 4
    writer.close()


def test_index_is_fully_rebuildable_from_jsonl_alone(tmp_path):
    """The §9 testing hook, exactly as stated: delete the SQLite index, regenerate it from
    the files, and confirm the same answers come back."""
    writer, index = _writer_with_index(tmp_path)
    _populate(writer)
    writer.close()
    before = index.locate(LogQuery(run_id="run-a", min_level=LogLevel.TRACE))
    index.close()

    db = tmp_path / "index.sqlite"
    for stray in tmp_path.glob("index.sqlite*"):  # WAL/SHM siblings too
        stray.unlink()
    assert not db.exists()

    rebuilt = LogIndex(db, root=tmp_path)
    result = rebuilt.rebuild()
    assert result.ok, result.error_detail
    assert result.entries_indexed == 4
    assert result.files_scanned == 2  # ocr and inference, one day each
    assert rebuilt.locate(LogQuery(run_id="run-a", min_level=LogLevel.TRACE)) == before
    rebuilt.close()


def test_rebuild_skips_a_truncated_final_line(tmp_path):
    """A process killed mid-append leaves a partial line. Losing that one entry is correct;
    failing the whole rebuild because of it is not."""
    writer, index = _writer_with_index(tmp_path)
    _populate(writer)
    writer.close()
    target = next((tmp_path / "ocr").iterdir())
    with open(target, "ab") as handle:
        handle.write(b'{"ts": "2026-07-17T08:0')
    result = index.rebuild()
    assert result.ok
    assert result.entries_indexed == 4
    index.close()


def test_rebuild_offsets_still_address_the_right_entries(tmp_path):
    """Byte offsets, not text-mode positions — a rebuilt index whose offsets are wrong is
    worse than no index at all, and on Windows a text-mode tell() is not a byte count."""
    writer, index = _writer_with_index(tmp_path)
    writer.write_sync(LogEntry(BASE, "run-x", "u", "ocr", LogLevel.INFO, "ascii"))
    writer.write_sync(LogEntry(BASE, "run-x", "u", "ocr", LogLevel.INFO, "peso ₱ 1,234.00"))
    writer.close()
    index.rebuild()
    from core.logs.query import _read_at
    from pathlib import Path

    located = index.locate(LogQuery(run_id="run-x", min_level=LogLevel.TRACE))
    messages = [_read_at(Path(p), o, n).message for p, o, n in located]
    assert messages == ["ascii", "peso ₱ 1,234.00"]
    index.close()


def test_prune_paths_drops_rows_for_deleted_files(tmp_path):
    writer, index = _writer_with_index(tmp_path)
    _populate(writer)
    writer.close()
    ocr_file = str(next((tmp_path / "ocr").iterdir()))
    assert index.prune_paths((ocr_file,)) == 3
    assert index.count() == 1
    index.close()


def test_an_unusable_index_degrades_rather_than_raising_at_the_writer(tmp_path):
    """Losing the index must cost a slower query later, never a failed log write now."""
    not_a_database = tmp_path / "index_is_a_directory"
    not_a_database.mkdir()
    index = LogIndex(not_a_database, root=tmp_path)
    assert not index.available
    registry = SinkRegistry()
    registry.register(JsonlFileSink(tmp_path))
    writer = LogWriter(tmp_path, registry=registry, index=index)
    assert writer.write_sync(
        LogEntry(BASE, "run-a", "u", "ocr", LogLevel.INFO, "still written")
    ).written
    writer.close()

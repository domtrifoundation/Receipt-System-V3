"""Sink registry and path-layout tests (§1.2, §1.6, §3.1)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from core.logs.contracts import LogEntry, LogLevel
from core.logs.metrics import COUNTER_NAMES, LogsMetricsCollector
from core.logs.paths import day_file, default_log_root, describe, iter_log_files
from core.logs.sinks import JsonlFileSink, MemorySink, SinkRegistry, default_registry

WHEN = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)


def _entry(service="ocr", level=LogLevel.INFO, message="m") -> LogEntry:
    return LogEntry(WHEN, "run-1", "user-1", service, level, message)


# ----------------------------------------------------------------------- paths


def test_log_root_never_defaults_inside_the_repository(monkeypatch):
    """`docs/PRINCIPLES.md` §1.6/§2.4 — V2 defaulted its data paths inside the program
    directory and committed real financial data into source history as a result. Logs carry
    real receipt content, so the default resolves outside the checkout, not into `data/`."""
    monkeypatch.delenv("RESIBO_LOG_ROOT", raising=False)
    monkeypatch.delenv("RESIBO_TOP_LEVEL", raising=False)
    repo = Path(__file__).resolve().parents[4]
    assert repo not in default_log_root().resolve().parents


def test_top_level_env_places_logs_beside_every_release_clone(monkeypatch, tmp_path):
    monkeypatch.delenv("RESIBO_LOG_ROOT", raising=False)
    monkeypatch.setenv("RESIBO_TOP_LEVEL", str(tmp_path))
    assert default_log_root() == tmp_path / "logs"


def test_describe_round_trips_both_tracks(tmp_path):
    ordinary = day_file(tmp_path, "ocr", date(2026, 7, 17))
    trace = day_file(tmp_path, "ocr", date(2026, 7, 17), trace=True)
    assert describe(ordinary) == ("ocr", date(2026, 7, 17), False)
    assert describe(trace) == ("ocr", date(2026, 7, 17), True)


def test_a_service_name_can_never_escape_the_log_root(tmp_path):
    """A service name is an internal identifier, but it still becomes a directory name."""
    path = day_file(tmp_path, "../../etc", date(2026, 7, 17))
    assert tmp_path in path.parents


def test_stray_files_in_the_log_root_are_ignored(tmp_path):
    sink = JsonlFileSink(tmp_path)
    sink.emit(_entry())
    sink.close()
    (tmp_path / "ocr" / "notes.txt").write_text("not a log file")
    assert [p.suffix for p in iter_log_files(tmp_path)] == [".jsonl"]


# ----------------------------------------------------------------------- sinks


def test_registry_runs_every_enabled_sink_and_can_disable_one(tmp_path):
    registry = default_registry(tmp_path)
    assert {s.name for s in registry.enabled()} == {"jsonl_file", "memory"}
    registry.disable("memory")
    assert {s.name for s in registry.enabled()} == {"jsonl_file"}
    assert registry.enable("memory") is True
    assert registry.enable("nonexistent") is False
    registry.close()


def test_memory_sink_is_a_bounded_buffer_not_a_store():
    sink = MemorySink(capacity=2)
    for i in range(5):
        sink.emit(_entry(message=f"m{i}"))
    assert [e.message for e in sink.recent()] == ["m3", "m4"]


def test_rotation_is_a_new_file_with_no_truncation_logic(tmp_path):
    sink = JsonlFileSink(tmp_path)
    first = sink.emit(LogEntry(WHEN, None, None, "ocr", LogLevel.INFO, "yesterday"))
    later = WHEN.replace(day=18)
    second = sink.emit(LogEntry(later, None, None, "ocr", LogLevel.INFO, "today"))
    sink.close()
    assert first.path != second.path
    assert second.offset == 0
    assert Path(first.path).read_bytes().count(b"\n") == 1
    assert len(list(iter_log_files(tmp_path))) == 2


def test_both_tracks_of_one_day_stay_open_together(tmp_path):
    """The trace split puts two files for one service in one directory, and OCR/Inference
    default to `trace` while still emitting INFO and ERROR — so the two tracks interleave
    constantly. Evicting handles by directory rather than by day made every single entry
    close and reopen the other track's file, on this API's two highest-volume services."""
    sink = JsonlFileSink(tmp_path)
    opened = []
    import builtins

    real_open = builtins.open
    def counting_open(*args, **kwargs):
        if args and str(args[0]).endswith(".jsonl"):
            opened.append(str(args[0]))
        return real_open(*args, **kwargs)

    builtins.open = counting_open
    try:
        for i in range(6):
            level = LogLevel.TRACE if i % 2 == 0 else LogLevel.INFO
            sink.emit(LogEntry(WHEN, None, None, "ocr", level, f"m{i}"))
    finally:
        builtins.open = real_open
    assert len(opened) == 2  # one per track, not one per entry
    sink.close()


def test_a_new_day_still_releases_the_previous_day_handles(tmp_path):
    """Evicting by day rather than by directory must not turn into never evicting: a
    long-running service would otherwise hold one handle per day open forever."""
    sink = JsonlFileSink(tmp_path)
    sink.emit(LogEntry(WHEN, None, None, "ocr", LogLevel.INFO, "yesterday"))
    sink.emit(LogEntry(WHEN, None, None, "ocr", LogLevel.TRACE, "yesterday raw"))
    assert len(sink._handles) == 2  # noqa: SLF001 - the handle cache is what is under test
    sink.emit(LogEntry(WHEN.replace(day=18), None, None, "ocr", LogLevel.INFO, "today"))
    assert [describe(p)[1].day for p in sink._handles] == [18]  # noqa: SLF001
    sink.close()


# --------------------------------------------------------------------- metrics


def test_counter_names_are_derived_from_the_contract():
    """Adding a counter means adding a field to `LogsMetrics` and nothing else — the two
    cannot drift apart."""
    assert "entries_written" in COUNTER_NAMES
    assert set(COUNTER_NAMES) == set(vars(LogsMetricsCollector().snapshot()))


def test_an_unknown_counter_name_never_takes_down_the_write_path():
    collector = LogsMetricsCollector()
    collector.increment("typo_that_does_not_exist")
    assert collector.snapshot().entries_written == 0

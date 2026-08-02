"""Write-path tests (§3.1, §3.3, §6).

The traceback-capture regression test below is the deep-dive's own first named testing hook
and the correction of a real V2 bug: V2 logged `str(e)`, which discards the line, the call
stack, and the chained-exception context — the only things that make a failure inside a
`run_in_executor`-dispatched call diagnosable at all.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from common.frozen_dict import FrozenDict
from core.logs.contracts import LogEntry, LogLevel, Verbosity
from core.logs.jsonl import decode
from core.logs.paths import day_file
from core.logs.sinks import JsonlFileSink, MemorySink, SinkRegistry
from core.logs.writer import LogWriter, format_traceback


def _writer(tmp_path, verbosity: Verbosity | None = None) -> LogWriter:
    registry = SinkRegistry()
    registry.register(JsonlFileSink(tmp_path))
    return LogWriter(tmp_path, verbosity=verbosity, registry=registry)


def _read_all(path):
    with open(path, "rb") as handle:
        return [decode(line) for line in handle if decode(line) is not None]


# --------------------------------------------------------------------- §3.1 storage


def test_writes_one_jsonl_file_per_service_per_day(tmp_path):
    writer = _writer(tmp_path)
    when = datetime(2026, 7, 17, 8, 30, tzinfo=timezone.utc)
    receipt = writer.write_sync(
        LogEntry(when, "run-1", "user-1", "ocr", LogLevel.INFO, "engine finished")
    )
    expected = day_file(tmp_path, "ocr", when)
    assert receipt.written and receipt.path == str(expected)
    assert [e.message for e in _read_all(expected)] == ["engine finished"]
    writer.close()


def test_appends_never_rewrite_and_offsets_address_each_entry(tmp_path):
    """The index stores byte offsets; if appending moved earlier entries, every stored
    offset would silently rot."""
    writer = _writer(tmp_path)
    when = datetime(2026, 7, 17, 8, 30, tzinfo=timezone.utc)
    first = writer.write_sync(LogEntry(when, None, None, "ocr", LogLevel.INFO, "one"))
    second = writer.write_sync(LogEntry(when, None, None, "ocr", LogLevel.INFO, "two"))
    assert second.offset == first.offset + first.length
    with open(first.path, "rb") as handle:
        handle.seek(second.offset)
        assert decode(handle.read(second.length)).message == "two"
    writer.close()


def test_trace_entries_land_in_their_own_short_retention_track(tmp_path):
    """§10 gives TRACE its own 7-day window. Splitting the tier into a sibling file is what
    makes that a file delete rather than an in-place rewrite of a mixed file."""
    writer = _writer(tmp_path, Verbosity(default=LogLevel.TRACE, per_service=FrozenDict({})))
    when = datetime(2026, 7, 17, 8, 30, tzinfo=timezone.utc)
    trace = writer.write_sync(LogEntry(when, None, None, "ocr", LogLevel.TRACE, "raw"))
    info = writer.write_sync(LogEntry(when, None, None, "ocr", LogLevel.INFO, "done"))
    assert trace.path.endswith(".trace.jsonl")
    assert not info.path.endswith(".trace.jsonl")
    writer.close()


# --------------------------------------------------------------- §8 verbosity tiers


def test_verbosity_drops_routine_entries_below_the_service_tier(tmp_path):
    writer = _writer(
        tmp_path, Verbosity(default=LogLevel.WARNING, per_service=FrozenDict({}))
    )
    when = datetime(2026, 7, 17, 8, 30, tzinfo=timezone.utc)
    dropped = writer.write_sync(LogEntry(when, None, None, "ocr", LogLevel.DEBUG, "chatter"))
    assert not dropped.written
    assert not dropped.error_code  # a drop is not a failure
    assert writer.metrics.snapshot().entries_dropped_by_verbosity == 1
    writer.close()


def test_per_service_override_beats_the_default(tmp_path):
    writer = _writer(
        tmp_path,
        Verbosity(default=LogLevel.WARNING, per_service=FrozenDict({"ocr": LogLevel.TRACE})),
    )
    when = datetime(2026, 7, 17, 8, 30, tzinfo=timezone.utc)
    assert writer.write_sync(
        LogEntry(when, None, None, "ocr", LogLevel.DEBUG, "engine detail")
    ).written
    assert not writer.write_sync(
        LogEntry(when, None, None, "billing", LogLevel.DEBUG, "chatter")
    ).written
    writer.close()


# ------------------------------------------------- §3.3 unconditional traceback capture


def test_traceback_is_written_at_a_tier_that_drops_everything_routine(tmp_path):
    """§3.3's hard requirement: tiers control *volume*, never whether a failure's traceback
    is recorded. A DEBUG entry is far below this tier and is still written because it
    carries one."""
    writer = _writer(
        tmp_path, Verbosity(default=LogLevel.ATTENTION, per_service=FrozenDict({}))
    )
    when = datetime(2026, 7, 17, 8, 30, tzinfo=timezone.utc)
    entry = LogEntry(
        when, None, None, "ocr", LogLevel.DEBUG, "failed", traceback="Traceback ...\n  boom"
    )
    assert writer.should_write(entry)
    assert writer.write_sync(entry).written
    assert writer.metrics.snapshot().tracebacks_captured == 1
    writer.close()


def test_full_traceback_from_an_exception_inside_run_in_executor(tmp_path):
    """The deep-dive's own §9 testing hook, and the V2 correction, in one test.

    The exception is raised **inside a `run_in_executor`-dispatched call** — the case §3.3
    names specifically, because that is where the traceback is both hardest to reconstruct
    and most necessary. What lands in the log must be the full formatted traceback including
    the raising frame, never `str(e)`.
    """
    writer = _writer(
        tmp_path, Verbosity(default=LogLevel.ATTENTION, per_service=FrozenDict({}))
    )

    def _inner_frame_that_raises():
        raise ValueError("engine returned no pages")

    async def _run():
        with pytest.raises(ValueError):
            await writer.guarded_call("ocr", _inner_frame_that_raises, run_id="run-9")

    asyncio.run(_run())

    written = _read_all(day_file(tmp_path, "ocr", datetime.now(timezone.utc)))
    assert len(written) == 1
    entry = written[0]
    assert entry.level is LogLevel.ERROR
    assert entry.run_id == "run-9"
    assert entry.traceback is not None
    # The three things str(e) throws away, asserted individually so a regression to
    # str(e)-style logging cannot pass this test by accident.
    assert "Traceback (most recent call last)" in entry.traceback
    assert "_inner_frame_that_raises" in entry.traceback
    assert "ValueError: engine returned no pages" in entry.traceback
    assert entry.traceback.strip() != "engine returned no pages"
    writer.close()


def test_format_traceback_keeps_chained_exception_context(tmp_path):
    """Chained context is part of what `str(e)` discards, and it is routinely the half that
    says what actually went wrong."""
    try:
        try:
            raise KeyError("vendor_tin")
        except KeyError as inner:
            raise RuntimeError("vendor lookup failed") from inner
    except RuntimeError as exc:
        text = format_traceback(exc)
    assert "KeyError" in text and "RuntimeError" in text
    assert "direct cause" in text


def test_log_exception_records_the_traceback_asynchronously(tmp_path):
    writer = _writer(tmp_path)

    async def _run():
        try:
            raise OSError("disk gone")
        except OSError as exc:
            return await writer.log_exception("persistence", "write failed", exc)

    receipt = asyncio.run(_run())
    assert receipt.written
    entry = _read_all(receipt.path)[0]
    assert "OSError: disk gone" in entry.traceback
    writer.close()


# ------------------------------------------------------------------ §4.4 degradation


def test_a_failing_sink_never_fails_the_caller(tmp_path):
    """Logging must not be able to fail the thing being logged. One broken sink degrades
    itself; the others keep the entry."""

    class BrokenSink:
        name = "broken"

        def emit(self, entry):
            from core.logs.errors import SinkWriteError

            raise SinkWriteError("permission denied")

        def close(self):
            pass

    registry = SinkRegistry()
    registry.register(BrokenSink())
    memory = MemorySink()
    registry.register(memory)
    writer = LogWriter(tmp_path, registry=registry)

    receipt = writer.write_sync(
        LogEntry(datetime.now(timezone.utc), None, None, "ocr", LogLevel.INFO, "still logged")
    )
    assert receipt.written
    assert [e.message for e in memory.recent()] == ["still logged"]
    assert writer.metrics.snapshot().sink_failures == 1


def test_a_sink_raising_something_other_than_sinkwriteerror_still_degrades_alone(tmp_path):
    """Sinks are a Provider Registry, so a sink is not necessarily one of this package's
    own — a forwarder to a self-hosted collector raises whatever its own HTTP library
    raises, not `SinkWriteError`. Catching only the internal type would let a third-party
    provider take down the run it was only supposed to be logging."""

    class RudeSink:
        name = "rude"

        def emit(self, entry):
            raise RuntimeError("collector refused the connection")

        def close(self):
            pass

    registry = SinkRegistry()
    registry.register(RudeSink())
    registry.register(JsonlFileSink(tmp_path))
    writer = LogWriter(tmp_path, registry=registry)

    receipt = writer.write_sync(
        LogEntry(datetime.now(timezone.utc), None, None, "ocr", LogLevel.INFO, "survived")
    )
    assert receipt.written and receipt.path
    assert writer.metrics.snapshot().sink_failures == 1
    writer.close()


def test_multiple_sinks_receive_the_same_entry(tmp_path):
    """`docs/PRINCIPLES.md` §1.2 — more than one provider runs at once where it adds real
    value, and a client attaching mid-run wanting recent entries without re-reading the file
    it just wrote is that value."""
    registry = SinkRegistry()
    registry.register(JsonlFileSink(tmp_path))
    memory = MemorySink()
    registry.register(memory)
    writer = LogWriter(tmp_path, registry=registry)
    receipt = writer.write_sync(
        LogEntry(datetime.now(timezone.utc), None, None, "ocr", LogLevel.INFO, "fanned out")
    )
    assert receipt.path  # the addressable sink is the one the index points at
    assert len(memory.recent()) == 1
    writer.close()


def test_write_is_dispatched_off_the_event_loop(tmp_path):
    """§6: rotated-file writes are non-blocking appends via `run_in_executor`."""
    writer = _writer(tmp_path)

    async def _run():
        return await writer.write(
            LogEntry(datetime.now(timezone.utc), None, None, "ocr", LogLevel.INFO, "async")
        )

    assert asyncio.run(_run()).written
    writer.close()

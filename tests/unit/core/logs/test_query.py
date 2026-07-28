"""Read-path tests (§4, §3.2).

Two properties matter here and they pull in opposite directions on purpose: the permission
gate fails closed (`docs/PRINCIPLES.md` §4.2) while everything else degrades gracefully
(§4.4). Both are tested, because getting either posture applied to the wrong half is exactly
the failure the two rules exist to separate.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from core.logs.contracts import LogEntry, LogLevel, LogQuery
from core.logs.errors import AccessCheckUnavailable
from core.logs.index import LogIndex
from core.logs.query import AuthBreakGlassChecker, DenyCrossUser, LogReader
from core.logs.sinks import JsonlFileSink, SinkRegistry
from core.logs.writer import LogWriter

BASE = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)


def _populated(tmp_path) -> LogIndex:
    index = LogIndex(tmp_path / "index.sqlite", root=tmp_path)
    registry = SinkRegistry()
    registry.register(JsonlFileSink(tmp_path))
    writer = LogWriter(tmp_path, registry=registry, index=index)
    rows = [
        ("ocr", LogLevel.INFO, "run-a", "user-1"),
        ("ocr", LogLevel.ERROR, "run-a", "user-1"),
        ("inference", LogLevel.INFO, "run-b", "user-2"),
        ("ocr", LogLevel.ATTENTION, "run-b", "user-2"),
    ]
    for i, (service, level, run_id, user_id) in enumerate(rows):
        writer.write_sync(
            LogEntry(BASE + timedelta(minutes=i), run_id, user_id, service, level, f"e{i}")
        )
    writer.close()
    return index


# ------------------------------------------------------------------ §4 permission gate


def test_a_user_may_read_their_own_logs(tmp_path):
    reader = LogReader(tmp_path, index=_populated(tmp_path))
    result = reader.read(
        LogQuery(user_id="user-1", requesting_user_id="user-1", min_level=LogLevel.TRACE)
    )
    assert result.ok
    assert {e.user_id for e in result.entries} == {"user-1"}


def test_cross_user_read_is_denied_by_default(tmp_path):
    """Fail closed: with no checker wired up, a cross-user read is denied. That is the
    correct behaviour for a Logs process running before Auth is reachable, not a degraded
    one — logs carry real receipt content."""
    reader = LogReader(tmp_path, index=_populated(tmp_path), checker=DenyCrossUser())
    result = reader.read(LogQuery(user_id="user-2", requesting_user_id="user-1"))
    assert not result.ok
    assert result.error_code == "CROSS_USER_ACCESS_DENIED"
    assert result.entries == ()


def test_unauthenticated_read_is_denied(tmp_path):
    reader = LogReader(tmp_path, index=_populated(tmp_path))
    assert reader.read(LogQuery(user_id="user-1")).error_code == "CROSS_USER_ACCESS_DENIED"


def test_all_user_read_is_itself_a_cross_user_read(tmp_path):
    """An omitted subject is not an exemption from the gate — it is the widest possible
    cross-user read and is gated as one."""
    reader = LogReader(tmp_path, index=_populated(tmp_path))
    assert reader.read(LogQuery(requesting_user_id="staff-1")).error_code == (
        "CROSS_USER_ACCESS_DENIED"
    )


def test_an_active_break_glass_grant_allows_the_cross_user_read(tmp_path):
    """The grant is Auth's own decision, reached through one adapter — Logs holds no notion
    of roles and invents no second permission mechanism."""
    checker = AuthBreakGlassChecker(lambda requester, subject: requester == "staff-1")
    reader = LogReader(tmp_path, index=_populated(tmp_path), checker=checker)
    result = reader.read(
        LogQuery(user_id="user-2", requesting_user_id="staff-1", min_level=LogLevel.TRACE)
    )
    assert result.ok
    assert {e.user_id for e in result.entries} == {"user-2"}


def test_an_unreachable_auth_denies_rather_than_permits(tmp_path):
    """§4.2 exactly: a security check that cannot be evaluated means unsafe, never a silent
    bypass. The distinct error code exists so an operator can tell an outage from a refusal."""

    def _explode(requester, subject):
        raise ConnectionError("auth unreachable")

    reader = LogReader(
        tmp_path, index=_populated(tmp_path), checker=AuthBreakGlassChecker(_explode)
    )
    result = reader.read(LogQuery(user_id="user-2", requesting_user_id="staff-1"))
    assert result.error_code == "ACCESS_CHECK_UNAVAILABLE"
    assert result.entries == ()


def test_denials_are_data_not_exceptions(tmp_path):
    """`docs/PRINCIPLES.md` §4.1 — Logs has no equivalent of Auth's raise-loudly carve-out
    at its own boundary; a caller checks `.error_code`."""
    reader = LogReader(tmp_path, index=_populated(tmp_path))
    result = reader.read(LogQuery(user_id="other", requesting_user_id="user-1"))
    assert isinstance(result.error_detail, str) and result.error_detail
    assert reader.metrics.snapshot().queries_denied == 1


# ------------------------------------------------------------------- §3.2 accelerator


def test_index_and_scan_return_identical_answers(tmp_path):
    """The claim that makes the index an accelerator rather than a source of truth: with no
    index at all, the same query returns the same entries."""
    index = _populated(tmp_path)
    query = LogQuery(run_id="run-a", requesting_user_id="user-1", user_id="user-1",
                     min_level=LogLevel.TRACE)

    via_index = LogReader(tmp_path, index=index).read(query)
    via_scan = LogReader(tmp_path, index=None).read(query)

    assert via_index.used_index and not via_scan.used_index
    assert [e.message for e in via_index.entries] == [e.message for e in via_scan.entries]
    assert via_scan.ok


def test_scan_fallback_is_counted_so_a_slow_query_is_diagnosable(tmp_path):
    _populated(tmp_path)
    reader = LogReader(tmp_path, index=None)
    reader.read(LogQuery(user_id="user-1", requesting_user_id="user-1"))
    assert reader.metrics.snapshot().index_fallback_scans == 1


def test_a_non_utc_time_bound_answers_identically_via_index_and_scan(tmp_path):
    """The index range-filters `ts` as *text*. A caller's own offset — `+08:00` is the
    obvious one for this project — compared raw against a `+00:00` column is a
    lexicographic comparison that is not a chronological one, and the index then returned
    nothing where the scan returned the entry. Two answers to one query is exactly what
    §3.2's "accelerator, not a source of truth" claim forbids."""
    index = _populated(tmp_path)
    manila = timezone(timedelta(hours=8))
    query = LogQuery(
        user_id="user-1",
        requesting_user_id="user-1",
        min_level=LogLevel.TRACE,
        # 10:00 +08:00 is 02:00 UTC — before every entry, which all sit at 08:00 UTC.
        since=datetime(2026, 7, 17, 10, 0, tzinfo=manila),
    )
    via_index = LogReader(tmp_path, index=index).read(query)
    via_scan = LogReader(tmp_path, index=None).read(query)
    assert via_index.used_index and not via_scan.used_index
    assert [e.message for e in via_index.entries] == [e.message for e in via_scan.entries]
    assert via_index.entries  # and the correct answer is not "nothing"


def test_a_naive_time_bound_is_answered_not_crashed(tmp_path):
    """`datetime.fromisoformat("2026-07-01")` — a perfectly ordinary wire value — is naive,
    and comparing it against an aware entry timestamp raises `TypeError` straight out of a
    boundary that returns errors as data rather than raising them (§4.1). Read as UTC."""
    index = _populated(tmp_path)
    query = LogQuery(
        user_id="user-1",
        requesting_user_id="user-1",
        min_level=LogLevel.TRACE,
        since=datetime(2026, 7, 17),  # naive on purpose
    )
    for reader in (LogReader(tmp_path, index=index), LogReader(tmp_path, index=None)):
        result = reader.read(query)
        assert result.ok, result.error_code
        assert [e.message for e in result.entries] == ["e0", "e1"]


def test_an_unexpected_failure_is_data_rather_than_an_escaped_exception(tmp_path):
    """`read()` is called straight from the gRPC servicer. Anything unanticipated becomes
    an `error_code` here or it becomes a gRPC status there."""
    reader = LogReader(tmp_path, index=_populated(tmp_path))

    def _explode(query):
        raise MemoryError("index blew up")

    reader._read_via_index = _explode  # noqa: SLF001 - simulating an unanticipated failure
    result = reader.read(LogQuery(user_id="user-1", requesting_user_id="user-1"))
    assert result.error_code == "READ_FAILED"
    assert "index blew up" in result.error_detail


def test_min_level_never_hides_attention(tmp_path):
    """ATTENTION outranks ERROR (§3.4), so "errors and worse" must include it."""
    reader = LogReader(tmp_path, index=_populated(tmp_path))
    checker = AuthBreakGlassChecker(lambda requester, subject: True)
    reader._checker = checker  # noqa: SLF001 - exercising the gate is not this test's point
    result = reader.read(LogQuery(requesting_user_id="staff-1", min_level=LogLevel.ERROR))
    assert {e.level for e in result.entries} == {LogLevel.ERROR, LogLevel.ATTENTION}


def test_limit_reports_truncation_rather_than_quietly_clipping(tmp_path):
    reader = LogReader(tmp_path, index=_populated(tmp_path))
    result = reader.read(
        LogQuery(user_id="user-1", requesting_user_id="user-1", min_level=LogLevel.TRACE,
                 limit=1)
    )
    assert len(result.entries) == 1
    assert result.truncated


def test_negative_limit_is_a_query_error_not_a_crash(tmp_path):
    reader = LogReader(tmp_path, index=_populated(tmp_path))
    assert reader.read(LogQuery(limit=-1)).error_code == "INVALID_QUERY"


def test_stream_yields_entries_for_the_server_streaming_rpc(tmp_path):
    reader = LogReader(tmp_path, index=_populated(tmp_path))

    async def _collect():
        return [
            item
            async for item in reader.stream(
                LogQuery(user_id="user-1", requesting_user_id="user-1",
                         min_level=LogLevel.TRACE)
            )
        ]

    items = asyncio.run(_collect())
    assert [i.message for i in items] == ["e0", "e1"]


def test_stream_yields_a_terminal_error_instead_of_raising(tmp_path):
    reader = LogReader(tmp_path, index=_populated(tmp_path))

    async def _collect():
        return [item async for item in reader.stream(LogQuery(requesting_user_id="staff-1"))]

    items = asyncio.run(_collect())
    assert len(items) == 1 and items[0].error_code == "CROSS_USER_ACCESS_DENIED"


def test_access_check_unavailable_is_its_own_internal_type():
    """Kept distinct internally even though both outcomes are denial — an outage and a
    refusal call for different operator responses."""
    assert issubclass(AccessCheckUnavailable, Exception)

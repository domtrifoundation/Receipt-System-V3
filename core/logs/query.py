"""Permission-gated read access (§4), index-accelerated with a scan fallback (§3.2).

Logs contain real receipt content — OCR text, LLM prompts quoting actual receipt data — so
read access follows the **identical** per-user model as Persistence and Search/Query: a
client reads their own logs; staff/owner cross-user access requires an active break-glass
grant, checked through Auth's own `check_access()` (Auth deep-dive §6.3). No second
permission mechanism is invented here, and this module deliberately owns no notion of roles.

Two postures sit side by side in this file and the difference is not accidental:

- The **permission gate fails closed** (`docs/PRINCIPLES.md` §4.2). No checker configured,
  the checker unreachable, an unauthenticated caller — all denied. An unavailable security
  check means unsafe, never a silent bypass.
- Everything **else degrades gracefully** (§4.4). No index, a corrupt index, a truncated
  final line — the query is answered by reading the JSONL files, which are the real data.
  The answer is identical; only the speed differs, and `LogQueryResult.used_index` reports
  which path ran so a slow query is diagnosable rather than mysterious.

Errors are data here, never raised across the boundary (§4.1): every path returns a
`LogQueryResult` carrying `error_code`/`error_detail`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, runtime_checkable

from .contracts import LEVEL_SEVERITY, LogEntry, LogQuery, LogQueryResult, as_utc
from .errors import (
    AccessCheckUnavailable,
    CrossUserAccessDenied,
    IndexUnavailable,
    InvalidQuery,
    code_for,
)
from .index import LogIndex
from .jsonl import decode
from .metrics import LogsMetricsCollector
from .paths import default_log_root, iter_log_files


@runtime_checkable
class AccessChecker(Protocol):
    """The one adapter seam onto Auth (`docs/PRINCIPLES.md` §1.3).

    Deliberately not an import of `core.auth`: Logs holds no opinion about roles or grants,
    only about whether this caller may read this subject's logs, which is a question Auth
    already answers. Keeping it a Protocol also means the gate is testable without standing
    up an Auth process.
    """

    def allow_cross_user(
        self, requesting_user_id: str | None, subject_user_id: str | None
    ) -> bool:
        """True only with an active break-glass grant. Raises `AccessCheckUnavailable`
        rather than returning False if it genuinely cannot tell — the caller treats both as
        denial, but only one of them is worth an operator's attention."""


class DenyCrossUser:
    """The default when nothing is wired up: own-user reads only.

    This is the fail-closed default (§4.2), not a placeholder to be replaced by something
    permissive. A Logs process running before Auth is reachable serves own-user reads and
    denies everything else, which is the correct behaviour, not a degraded one.
    """

    def allow_cross_user(self, requesting_user_id, subject_user_id) -> bool:
        return False


class AuthBreakGlassChecker:
    """Adapts Auth's own `check_access()` without importing it.

    `check` is supplied by whatever holds the Auth gRPC client — a callable taking
    `(requesting_user_id, subject_user_id)` and returning a bool. When Auth's own
    `contracts.py` exists, this is the single file that changes to call it directly.
    """

    def __init__(self, check) -> None:
        self._check = check

    def allow_cross_user(self, requesting_user_id, subject_user_id) -> bool:
        try:
            return bool(self._check(requesting_user_id, subject_user_id))
        except Exception as exc:  # noqa: BLE001 - any failure is "cannot tell", i.e. denial
            raise AccessCheckUnavailable(str(exc)) from exc


class LogReader:
    """Serves `LogQuery` against the JSONL files, using the index when it is usable."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        index: LogIndex | None = None,
        checker: AccessChecker | None = None,
        metrics: LogsMetricsCollector | None = None,
    ) -> None:
        self._root = Path(root) if root else default_log_root()
        self._index = index
        self._checker: AccessChecker = checker or DenyCrossUser()
        self._metrics = metrics or LogsMetricsCollector()

    @property
    def metrics(self) -> LogsMetricsCollector:
        return self._metrics

    # ------------------------------------------------------------------ the gate
    def authorize(self, query: LogQuery) -> None:
        """Raise if this caller may not read this subject's logs. Fails closed."""
        requester = query.requesting_user_id
        subject = query.user_id
        if requester is not None and subject is not None and requester == subject:
            return
        if requester is None:
            raise CrossUserAccessDenied(
                "an unauthenticated caller may not read logs; logs carry receipt content"
            )
        if not self._checker.allow_cross_user(requester, subject):
            raise CrossUserAccessDenied(
                f"{requester!r} has no active break-glass grant for "
                f"{subject if subject is not None else 'all users'}"
            )

    # ------------------------------------------------------------------ read path
    def read(self, query: LogQuery) -> LogQueryResult:
        """The blocking read. Returns a result object on every path, never raises."""
        if query.limit < 0:
            return LogQueryResult(
                error_code=code_for(InvalidQuery()), error_detail="limit must not be negative"
            )
        try:
            self.authorize(query)
        except (CrossUserAccessDenied, AccessCheckUnavailable) as exc:
            self._metrics.increment("queries_denied")
            return LogQueryResult(error_code=code_for(exc), error_detail=str(exc))

        used_index = True
        try:
            try:
                entries = self._read_via_index(query)
            except IndexUnavailable:
                used_index = False
                self._metrics.increment("index_fallback_scans")
                entries = self._read_via_scan(query)
        except Exception as exc:  # noqa: BLE001
            # The outer catch is the boundary guarantee itself, not defensiveness: this
            # method is called straight from the gRPC servicer, and §4.1 says a caller
            # checks `.error_code` rather than wrapping the call in try/except. Anything
            # unanticipated becomes data here or it becomes a gRPC status there. The
            # fallback scan is deliberately inside it too — it is reached from an `except`
            # block, so a failure of its own would otherwise escape entirely.
            return LogQueryResult(error_code="READ_FAILED", error_detail=str(exc))

        truncated = len(entries) > query.limit
        self._metrics.increment("queries_served")
        return LogQueryResult(
            entries=tuple(entries[: query.limit]),
            truncated=truncated,
            used_index=used_index,
        )

    async def read_async(self, query: LogQuery) -> LogQueryResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.read, query)

    async def stream(self, query: LogQuery):
        """Async generator behind the server-streaming `Query` RPC (§7).

        The whole result is resolved first and then yielded entry by entry: a query is
        bounded by `limit`, and the alternative — holding file handles open across an await
        while a client consumes at its own pace — makes a slow or vanished client able to
        pin resources in a service that is supposed to be entirely indifferent to whether a
        client exists at all (§1, §1.7).
        """
        result = await self.read_async(query)
        if not result.ok:
            yield result
            return
        for entry in result.entries:
            yield entry

    # ------------------------------------------------------------------ internals
    def _read_via_index(self, query: LogQuery) -> list[LogEntry]:
        if self._index is None or not self._index.available:
            raise IndexUnavailable("no index configured")
        entries: list[LogEntry] = []
        for path, offset, length in self._index.locate(query):
            entry = _read_at(Path(path), offset, length)
            # Re-filtered even though the index already did: the files are the source of
            # truth, so an index row that has drifted must never be able to widen an answer.
            if entry is not None and matches(entry, query):
                entries.append(entry)
        entries.sort(key=lambda e: e.timestamp)
        return entries

    def _read_via_scan(self, query: LogQuery) -> list[LogEntry]:
        """The fallback that keeps §3.2's claim honest: everything is answerable from the
        JSONL files alone, with no index in existence at all."""
        entries: list[LogEntry] = []
        ceiling = query.limit + 1 if query.limit else None
        for path in iter_log_files(self._root, query.service):
            try:
                with open(path, "rb") as handle:
                    for raw in handle:
                        entry = decode(raw)
                        if entry is not None and matches(entry, query):
                            entries.append(entry)
            except OSError:
                continue  # a file deleted by retention mid-scan is not a failed query
        entries.sort(key=lambda e: e.timestamp)
        return entries[:ceiling] if ceiling else entries


def matches(entry: LogEntry, query: LogQuery) -> bool:
    """One filter predicate, used by both read paths — so both genuinely answer the same
    question rather than two similar ones that could drift apart."""
    if entry.severity < LEVEL_SEVERITY[query.min_level]:
        return False
    if query.run_id is not None and entry.run_id != query.run_id:
        return False
    if query.user_id is not None and entry.user_id != query.user_id:
        return False
    if query.service is not None and entry.service != query.service:
        return False
    # Both sides through `as_utc` before either comparison: a naive bound would otherwise
    # raise `TypeError` out of a boundary that returns errors as data, and a non-UTC bound
    # would answer differently here than the index's own text comparison does.
    when = as_utc(entry.timestamp)
    if query.since is not None and when < as_utc(query.since):
        return False
    if query.until is not None and when > as_utc(query.until):
        return False
    return True


def _read_at(path: Path, offset: int, length: int) -> LogEntry | None:
    """One entry by byte address. A line that no longer decodes is skipped, never fatal."""
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            return decode(handle.read(length))
    except OSError:
        return None


__all__ = [
    "AccessChecker",
    "AuthBreakGlassChecker",
    "DenyCrossUser",
    "LogReader",
    "matches",
]

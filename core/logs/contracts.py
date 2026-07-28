"""Logs API data contracts (`v3-deepdive-18-logs-api.md` §3, §4, §7, §8).

Types only, no logic beyond pure accessors — this is the single module other packages
import from (`docs/PRINCIPLES.md` §1.1). Nothing outside `core/logs/` should ever need to
import `writer`, `index`, `query`, or `service`.

Every type here is `@dataclass(frozen=True)` and every dict-typed field is a `FrozenDict`
(§2.1): a frozen dataclass holding a plain `dict` is only shallowly immutable, and a
`LogEntry`'s structured context crosses a process boundary. `LEVEL_STYLE_HINT` and
`LEVEL_SEVERITY` are module-level lookup tables and are therefore `FrozenDict` too — §2.1.1
was written from this module as one of its two motivating instances.

**`isinstance` against any of these must test `collections.abc.Mapping`, never `dict`.** The
Python 3.15 builtin `frozendict` is not a `dict` subclass, so `isinstance(x, dict)` silently
returns False and the wrong branch is taken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    """Timezone-aware UTC. Log timestamps are never naive — a JSONL line whose timestamp
    cannot be ordered against one written by another service's own process is useless for
    exactly the cross-service debugging this API exists for."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """The same instant in UTC, treating a naive value as already-UTC.

    Every timestamp this API compares or stores goes through here first, and that is a
    correctness requirement rather than tidiness. A client is free to send `since`/`until`
    in its own offset (`+08:00` is the obvious one here) or, over the wire, with no offset
    at all; without normalisation a naive value makes an aware/naive comparison raise
    `TypeError` straight out of a boundary that promises to return errors as data (§4.1),
    and a non-UTC offset makes the index's own string comparison disagree with the scan
    path's datetime comparison — two answers to one query, which is precisely what §3.2's
    "accelerator, not a source of truth" claim forbids.

    Naive means UTC rather than local: everything this API writes is `utcnow()`, and
    guessing at the reader's local zone would silently shift a window by hours. An
    already-aware value is genuinely *converted*, not merely accepted — returning it in its
    own offset would leave `utc_iso` below emitting a string that sorts against the stored
    rows lexicographically but not chronologically, which is the whole failure this exists
    to close.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_iso(value: datetime) -> str:
    """The sortable, storable form of a timestamp: UTC, ISO-8601.

    The index orders and range-filters on this as *text*, so every row has to carry the same
    offset for a lexicographic comparison to mean what a chronological one does.
    """
    return as_utc(value).isoformat()


class LogLevel(str, Enum):
    """Verbosity tiers (§3.1).

    `ATTENTION` is a genuinely new level, not a renamed `WARNING` (§3.4): it means "this
    process is running below its own achievable baseline", categorically different from
    "an operation failed" (`ERROR`) or "something is worth noting" (`WARNING`).
    """

    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    ATTENTION = "attention"


#: Ordering for min-level filtering. `ATTENTION` sits above `ERROR` deliberately: a client
#: asking for "errors and worse" must never be handed a stream that silently omits the one
#: level §3.4 says should be *harder* to miss than an error.
LEVEL_SEVERITY: FrozenDict = FrozenDict(
    {
        LogLevel.TRACE: 10,
        LogLevel.DEBUG: 20,
        LogLevel.INFO: 30,
        LogLevel.WARNING: 40,
        LogLevel.ERROR: 50,
        LogLevel.ATTENTION: 60,
    }
)

#: A rendering *hint*, owned here where the level itself is defined — not duplicated as a
#: second, independently-maintained opinion inside whatever client happens to render it
#: (§3.1, §3.4). This is metadata Logs API publishes, not rendering Logs API performs: the
#: client translates each hint into whatever its own technology can express (Rich markup for
#: a terminal client, something else entirely for one that is not a terminal). Logs API
#: never renders anything and does not know Interface exists.
LEVEL_STYLE_HINT: FrozenDict = FrozenDict(
    {
        LogLevel.TRACE: "dim",
        LogLevel.DEBUG: "subdued",
        LogLevel.INFO: "default",
        LogLevel.WARNING: "caution",
        LogLevel.ERROR: "critical",
        # Deliberately distinct from "critical": a client should render this as harder to
        # miss than ERROR, per §3.4.
        LogLevel.ATTENTION: "critical_persistent",
    }
)


@dataclass(frozen=True)
class LogEntry:
    """One structured operational-trace record — the unit written, indexed, and streamed.

    `traceback` carries the *full* formatted traceback text, never `str(e)` (§3.3). That
    capture is unconditional: verbosity tiers control the volume of routine logging and
    never gate whether a failure's traceback is recorded.

    `context` is the structured half of "structured/queryable" (§3.2) — per-entry key/values
    such as OCR engine timings — and is a `FrozenDict` rather than a plain `dict` for the
    shallow-immutability reason in this module's docstring.
    """

    timestamp: datetime
    run_id: str | None
    user_id: str | None
    service: str
    level: LogLevel
    message: str
    traceback: str | None = None
    context: FrozenDict = field(default_factory=lambda: FrozenDict({}))

    @property
    def severity(self) -> int:
        return LEVEL_SEVERITY[self.level]

    @property
    def suggested_style(self) -> str:
        """The §3.1 rendering hint for this entry's own level."""
        return LEVEL_STYLE_HINT[self.level]


@dataclass(frozen=True)
class Verbosity:
    """The §8 config block: a default tier plus per-service overrides.

    OCR and Inference default to `trace` because their raw output is genuinely high-volume
    and genuinely the thing being debugged — the override exists so that does not force
    every other service's own tier down with it.
    """

    default: LogLevel = LogLevel.INFO
    per_service: FrozenDict = field(
        default_factory=lambda: FrozenDict(
            {"ocr": LogLevel.TRACE, "inference": LogLevel.TRACE}
        )
    )

    def level_for(self, service: str) -> LogLevel:
        return self.per_service.get(service, self.default)


@dataclass(frozen=True)
class RetentionPolicy:
    """§5 and §10. Two windows, not one.

    `retention_days` is a pure operational-cost tradeoff (disk vs. debugging lookback) —
    unlike Audit's own retention, operational trace carries no compliance obligation, so a
    default is reasonable to set rather than a legal question to escalate.
    `trace_retention_days` is §10's resolved answer to TRACE-tier volume: raw OCR/LLM output
    is useful for immediate debugging, not as a long-term record.
    """

    retention_days: int = 90
    trace_retention_days: int = 7


@dataclass(frozen=True)
class LogQuery:
    """A read request (§4, §7). Carries who is asking, not just what is asked for.

    `requesting_user_id` is the *authenticated caller*; `user_id` is the subject whose logs
    are wanted. When they differ, the read is a cross-user read and needs an active
    break-glass grant checked through Auth — never a permission mechanism invented here.
    """

    run_id: str | None = None
    user_id: str | None = None
    service: str | None = None
    min_level: LogLevel = LogLevel.INFO
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 1000
    requesting_user_id: str | None = None


@dataclass(frozen=True)
class LogQueryResult:
    """Errors are data at this boundary, never raised across it (`docs/PRINCIPLES.md` §4.1)."""

    entries: tuple[LogEntry, ...] = ()
    error_code: str = ""
    error_detail: str = ""
    truncated: bool = False
    #: True when the index answered the query; False when it was answered by scanning the
    #: JSONL directly because the index was missing or unusable. The answer is identical
    #: either way — this reports *how*, so a slow query is diagnosable rather than
    #: mysterious, and so §3.2's "accelerator, not a source of truth" claim is observable.
    used_index: bool = True

    @property
    def ok(self) -> bool:
        return not self.error_code


@dataclass(frozen=True)
class WriteReceipt:
    """Where an accepted entry actually landed, so the index can point at it.

    `written=False` with an empty `error_code` is the ordinary verbosity-drop case, not a
    failure — a routine entry below its service's own tier. A real failure carries a code.
    """

    written: bool
    path: str = ""
    offset: int = 0
    length: int = 0
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class IndexRebuildResult:
    """§3.2's design claim, made checkable: the index is rebuildable from JSONL alone."""

    files_scanned: int = 0
    entries_indexed: int = 0
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code


@dataclass(frozen=True)
class PurgeResult:
    """§5's retention sweep, run by a Background Workers idle-time job — never by the write
    path, which stays a pure append."""

    files_deleted: tuple[str, ...] = ()
    index_rows_pruned: int = 0
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code


@dataclass(frozen=True)
class LogsMetrics:
    """An immutable snapshot of the counters `metrics.py` keeps."""

    entries_written: int = 0
    entries_dropped_by_verbosity: int = 0
    tracebacks_captured: int = 0
    sink_failures: int = 0
    index_records: int = 0
    index_fallback_scans: int = 0
    queries_served: int = 0
    queries_denied: int = 0
    files_purged: int = 0


__all__ = [
    "LEVEL_SEVERITY",
    "LEVEL_STYLE_HINT",
    "IndexRebuildResult",
    "LogEntry",
    "LogLevel",
    "LogQuery",
    "LogQueryResult",
    "LogsMetrics",
    "PurgeResult",
    "RetentionPolicy",
    "Verbosity",
    "WriteReceipt",
    "as_utc",
    "utc_iso",
    "utcnow",
]

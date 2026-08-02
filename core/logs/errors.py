"""Logs API error taxonomy.

These are surfaced as `error_code`/`error_detail` on the result contracts rather than raised
across the API boundary (`docs/PRINCIPLES.md` §4.1). They exist as real types because the
*internal* call path still benefits from telling them apart — a sink that cannot write and a
caller denied a cross-user read are different problems with different operator responses.

Logs API has no equivalent of Auth's raise-loudly carve-out. There is nothing in operational
trace whose failure is better handled by taking the caller down: a log write that fails must
never be able to fail the run that was being logged, which is the entire point of §4.4's
graceful-degradation posture applied here.

The one place this API is deliberately *not* graceful is the cross-user permission gate in
`query.py`: with no access checker wired up, a cross-user read is denied, never allowed
(`docs/PRINCIPLES.md` §4.2 — fail closed on security checks, degrade everywhere else).
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class LogsError(Exception):
    """Base for everything this API raises internally, never across its boundary."""


class SinkWriteError(LogsError):
    """A configured sink could not accept an entry.

    Degrades that sink, never the caller's run: `writer.py` records the failure in metrics
    and keeps going with whatever other sinks are enabled (§4.4).
    """


class IndexUnavailable(LogsError):
    """The SQLite query index could not be opened or read.

    Not fatal by construction: the index is a query accelerator over the JSONL files, never
    a second source of truth (§3.2), so `query.py` falls back to scanning the files and
    returns the identical answer more slowly.
    """


class LogRootMissing(LogsError):
    """The configured log root does not exist and could not be created."""


class CrossUserAccessDenied(LogsError):
    """A read of another user's logs without an active break-glass grant (§4).

    Logs contain real receipt content — OCR text, LLM prompts quoting actual receipt data —
    so read access follows the identical per-user model as Persistence, gated through Auth's
    own `check_access()`, not a second mechanism invented here.
    """


class AccessCheckUnavailable(LogsError):
    """Auth could not be reached to evaluate a cross-user read.

    Treated as denial, never as permission. This is the §4.2 fail-closed rule: an
    unavailable security check means unsafe, never a silent bypass.
    """


class InvalidQuery(LogsError):
    """A malformed read request — an unknown level string, a negative limit."""


#: Stable wire codes for the `.proto` surface's own `error_code` field (§7). Field-only-append
#: discipline applies here the same way it does to the `.proto`: a code is added, never
#: renamed, because a client may be matching on it.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        SinkWriteError: "SINK_WRITE_FAILED",
        IndexUnavailable: "INDEX_UNAVAILABLE",
        LogRootMissing: "LOG_ROOT_MISSING",
        CrossUserAccessDenied: "CROSS_USER_ACCESS_DENIED",
        AccessCheckUnavailable: "ACCESS_CHECK_UNAVAILABLE",
        InvalidQuery: "INVALID_QUERY",
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped.

    Unmapped is deliberately not an exception of its own: a caller receiving `INTERNAL` with
    a real detail string is strictly better off than one receiving a crash from the error
    path itself.
    """
    return ERROR_CODES.get(type(exc), "INTERNAL")


__all__ = [
    "ERROR_CODES",
    "AccessCheckUnavailable",
    "CrossUserAccessDenied",
    "IndexUnavailable",
    "InvalidQuery",
    "LogRootMissing",
    "LogsError",
    "SinkWriteError",
    "code_for",
]

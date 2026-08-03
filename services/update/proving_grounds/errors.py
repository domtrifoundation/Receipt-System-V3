"""Proving Grounds' error taxonomy.

Surfaced as `error_code`/`error_detail` on `TestResult`/`DownloadResult` rather than
raised across this sub-API's boundary (`docs/PRINCIPLES.md` §4.1) — a failed download or
an unavailable bench dispatcher is an ordinary, expected outcome, never a reason to take
this whole service down.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class ProvingGroundsInternalError(Exception):
    """Base for everything this package raises internally, never across its boundary."""


class DownloadFailed(ProvingGroundsInternalError):
    """The candidate's own download could not complete — a bad URL, a network failure, or
    an HF-gated model rejecting the supplied token."""


class NoBenchDispatcherForApi(ProvingGroundsInternalError):
    """No registered bench-suite dispatcher answers `TestCandidate.affected_api` — §1's own
    boundary ("reuses each affected API's own bench workload") has nothing to reuse yet for
    that API. Reported honestly rather than silently substituting a generic smoke test."""


class ContainerRunnerUnavailable(ProvingGroundsInternalError):
    """§8's resolved isolation mechanism (Docker) is not reachable on this host — the
    `docker` binary is missing, or the daemon is not running. A candidate cannot be tested
    without real isolation; this is never silently downgraded to running the bench suite
    unisolated."""


class BenchDispatchRaised(ProvingGroundsInternalError):
    """A registered bench dispatcher's own `run_bench()` raised — converted to data here,
    the one place a dispatcher's exception is caught (`docs/PRINCIPLES.md` §4.1), matching
    `core/tool_call/dispatch.py`'s identical posture for its own registered handlers."""


ERROR_CODES: FrozenDict = FrozenDict(
    {
        DownloadFailed: "DOWNLOAD_FAILED",
        NoBenchDispatcherForApi: "NO_BENCH_DISPATCHER",
        ContainerRunnerUnavailable: "CONTAINER_RUNNER_UNAVAILABLE",
        BenchDispatchRaised: "BENCH_DISPATCH_RAISED",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "DOWNLOAD_FAILED": "The candidate's own download did not complete.",
        "NO_BENCH_DISPATCHER": "No registered bench-suite dispatcher answers this candidate's affected_api.",
        "CONTAINER_RUNNER_UNAVAILABLE": "Docker is not reachable on this host; the candidate cannot be tested in isolation.",
        "BENCH_DISPATCH_RAISED": "The registered bench dispatcher raised instead of returning a result.",
        "INTERNAL": "An unmapped internal error.",
    }
)


def code_for(exc: BaseException) -> str:
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    return ERROR_SUMMARIES.get(code, ERROR_SUMMARIES["INTERNAL"])


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "BenchDispatchRaised",
    "ContainerRunnerUnavailable",
    "DownloadFailed",
    "NoBenchDispatcherForApi",
    "ProvingGroundsInternalError",
    "code_for",
    "summary_for",
]

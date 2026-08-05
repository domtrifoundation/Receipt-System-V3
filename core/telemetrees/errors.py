"""Telemetrees error taxonomy.

Surfaced as data on `PollResult.unreachable` and the result contracts rather than raised
across the API boundary (`docs/PRINCIPLES.md` §4.1).

**The posture here is graceful degradation, with no fail-closed exception anywhere** — and
that is worth stating because most packages in this project have one. Telemetrees watches
things; it gates nothing. An unreachable PyPI, a GitHub API rate limit, a community tracker
that moved: each costs one fact one cycle, and the correct response is to record that the
fact could not be observed and keep polling everything else. Monitoring that stopped when one
source became unreachable would silently take every *other* dependency's tracking down with
it, which is the opposite of what a monitoring system exists to do.

The one thing this package must never do is report a fact it did not actually observe. An
unreachable poller yields no fact rather than a stale or guessed one — the same discipline
Health's capability drift check follows, and for the same reason: a clean-looking answer from
a check that did not run is worse than an obvious gap.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class TelemetreesError(Exception):
    """Base for everything this API raises internally, never across its boundary."""


class UnknownDependency(TelemetreesError):
    """A poll or query naming a dependency the registry does not track."""


class UpstreamUnreachable(TelemetreesError):
    """PyPI, GitHub or the community tracker could not be reached.

    Degrades that one fact for that one cycle. Never fails the pass, and never resolves to a
    value — an unobserved fact is absent, not assumed unchanged.
    """


class MalformedUpstreamResponse(TelemetreesError):
    """A reachable source returned something this poller could not read.

    Deliberately distinct from `UpstreamUnreachable`: an API that answered with a shape we did
    not expect usually means it changed, which is a different problem from a network blip and
    wants a different investigation.
    """


class InvalidIssueRef(TelemetreesError):
    """An `upstream_issue_refs` entry that is not `owner/repo#number`."""


class ChangelogUnwritable(TelemetreesError):
    """`docs/CHANGELOG.md` could not be written.

    Never fails the poll that produced the entry: the tracked state is still updated, and a
    changelog write failing must not lose the observation itself.
    """


ERROR_CODES: FrozenDict = FrozenDict(
    {
        UnknownDependency: "UNKNOWN_DEPENDENCY",
        UpstreamUnreachable: "UPSTREAM_UNREACHABLE",
        MalformedUpstreamResponse: "MALFORMED_UPSTREAM_RESPONSE",
        InvalidIssueRef: "INVALID_ISSUE_REF",
        ChangelogUnwritable: "CHANGELOG_UNWRITABLE",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "UNKNOWN_DEPENDENCY": "That dependency is not in the tracked registry.",
        "UPSTREAM_UNREACHABLE": "The upstream source could not be reached this cycle.",
        "MALFORMED_UPSTREAM_RESPONSE": "The upstream source returned an unreadable response.",
        "INVALID_ISSUE_REF": "An issue reference is not in owner/repo#number form.",
        "CHANGELOG_UNWRITABLE": "The changelog could not be written; tracking was still updated.",
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
    "ChangelogUnwritable",
    "InvalidIssueRef",
    "MalformedUpstreamResponse",
    "TelemetreesError",
    "UnknownDependency",
    "UpstreamUnreachable",
    "code_for",
    "summary_for",
]

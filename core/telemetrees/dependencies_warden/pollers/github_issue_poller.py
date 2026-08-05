"""The `upstream_issue_status` fact kind — one specific issue's state (Warden §3, parent §3.2).

Parent §3.2 spells out why this is a distinct fact kind rather than something release
monitoring could cover: "a plain release-version poller would never surface 'the free-threaded
-wheel blocker is still open' — that fact lives on a GitHub issue, not in a release changelog,
and could resolve either *with* or *independent of* a version bump."

`opencv/opencv#27933` is the concrete case the whole distinction was drawn from, and it is in
the shipped inventory. Telemetrees §8's issue-state-change hook tests exactly this path: an
issue going open→closed must surface as a changelog event rather than being silently missed.

**Authentication is the caller's problem, not this module's**, and the parent's `CLAUDE.md`
already states the rule — a GitHub App scoped to nothing but what it needs, never a personal
access token. That belongs in whichever transport a deployment injects; putting credential
handling here would spread it across every poller that talks to GitHub instead of containing
it in the one adapter (`docs/PRINCIPLES.md` §1.3).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ...contracts import IssueState, IssueStateEvent
from ...errors import InvalidIssueRef, MalformedUpstreamResponse
from .base import HttpTransport, UnavailableTransport

GITHUB_ISSUE_URL = "https://api.github.com/repos/{owner}/{repo}/issues/{number}"

#: `owner/repo#number`. The inventory carries `opencv/opencv-python#1051`, so a repo name may
#: itself contain a hyphen — the pattern allows the full set of characters GitHub permits
#: rather than assuming a simple word.
_ISSUE_REF = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")


def parse_issue_ref(issue_ref: str) -> tuple[str, str, str]:
    """`owner/repo#number` into its parts, or raise.

    Raising rather than returning `None` on a malformed ref is deliberate: a typo'd reference
    in the registry means a fact nobody is watching while the inventory claims otherwise, and
    that should fail loudly at the point of use rather than resolve to a quiet "no event".
    """
    match = _ISSUE_REF.match(issue_ref.strip())
    if not match:
        raise InvalidIssueRef(f"{issue_ref!r} is not in owner/repo#number form")
    return match.group("owner"), match.group("repo"), match.group("number")


class GitHubIssuePoller:
    """Checks one specific issue's open/closed state (Warden §3)."""

    fact_kind_name = "upstream_issue_status"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._transport: HttpTransport = transport or UnavailableTransport()

    def poll(self, dep_name: str, issue_ref: str) -> IssueStateEvent | None:
        """That issue's current state.

        An unrecognised `state` string resolves to `IssueState.UNKNOWN` rather than being
        guessed at as open or closed. GitHub's own vocabulary can grow, and reporting a state
        we did not understand as "still open" would keep a resolved blocker looking unresolved
        — precisely the signal this poller exists to deliver.
        """
        owner, repo, number = parse_issue_ref(issue_ref)
        payload = self._transport.get_json(
            GITHUB_ISSUE_URL.format(owner=owner, repo=repo, number=number)
        )
        if not isinstance(payload, Mapping):
            raise MalformedUpstreamResponse(f"GitHub returned a non-object for {issue_ref!r}")

        raw_state = str(payload.get("state", "")).lower()
        try:
            state = IssueState(raw_state)
        except ValueError:
            state = IssueState.UNKNOWN

        return IssueStateEvent(
            dependency=dep_name,
            issue_ref=issue_ref,
            state=state,
            title=str(payload.get("title", "")),
            url=str(payload.get("html_url", "")),
        )


__all__ = ["GITHUB_ISSUE_URL", "GitHubIssuePoller", "parse_issue_ref"]

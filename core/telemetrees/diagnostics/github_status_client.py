"""A real, read-only GitHub REST client for the *status* half of issue tracking —
whether a filed issue is still open, and which pull requests reference it. Deliberately
unauthenticated: reading a public issue's state and its cross-references needs no
credential at all, and this project holds no GitHub token for read-only status checks
(`docs/PRINCIPLES.md` §1.3 — one small internal adapter in front of an external service,
never scattered raw HTTP calls at call sites).

**Filing a new issue is not this module's job.** That needs a real GitHub App
installation token this codebase does not have and should not fabricate — the same
credential boundary every other external-service integration in this project respects.
This client only ever reads.
"""

from __future__ import annotations

import httpx

from .contracts import IssueStatus, utcnow

__all__ = ["GitHubIssueStatusClient"]

_API_ROOT = "https://api.github.com"


class GitHubIssueStatusClient:
    def __init__(self, owner: str, repo: str, *, timeout_seconds: float = 10.0) -> None:
        self._owner = owner
        self._repo = repo
        self._timeout = timeout_seconds

    async def get_status(self, issue_number: int) -> IssueStatus:
        """Never raises — a network failure, a deleted issue, or a rate limit all come
        back as `IssueStatus(error_detail=...)` rather than an exception, since a status
        panel showing "couldn't check" is real, useful information, and matches this
        project's own errors-are-data discipline (`docs/PRINCIPLES.md` §4.1) even though
        this call crosses a real network boundary rather than an internal gRPC one."""
        checked_at = utcnow()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{_API_ROOT}/repos/{self._owner}/{self._repo}/issues/{issue_number}",
                    headers={"Accept": "application/vnd.github+json"},
                )
                if response.status_code != 200:
                    return IssueStatus(
                        issue_number=issue_number, state="", title="", url="", checked_at=checked_at,
                        error_detail=f"GitHub returned {response.status_code} for issue #{issue_number}",
                    )
                data = response.json()
                linked = await self._linked_pull_requests(client, issue_number)
        except httpx.HTTPError as exc:
            return IssueStatus(
                issue_number=issue_number, state="", title="", url="", checked_at=checked_at,
                error_detail=f"could not reach GitHub: {exc}",
            )

        return IssueStatus(
            issue_number=issue_number, state=data.get("state", ""), title=data.get("title", ""),
            url=data.get("html_url", ""), linked_pr_numbers=linked, checked_at=checked_at,
        )

    async def _linked_pull_requests(self, client: httpx.AsyncClient, issue_number: int) -> tuple[int, ...]:
        """Real cross-reference data from GitHub's own Timeline API — `"cross-referenced"`
        events whose source is a pull request are exactly what "a PR fix is being
        developed for this issue" means on GitHub's own model. Degrades to an empty tuple
        on any failure here specifically (a timeline lookup failing should not blank out
        the issue's own real state, already fetched successfully by the caller)."""
        try:
            response = await client.get(
                f"{_API_ROOT}/repos/{self._owner}/{self._repo}/issues/{issue_number}/timeline",
                headers={"Accept": "application/vnd.github+json"},
            )
            if response.status_code != 200:
                return ()
            events = response.json()
        except httpx.HTTPError:
            return ()

        numbers: list[int] = []
        for event in events:
            if event.get("event") != "cross-referenced":
                continue
            source = event.get("source", {})
            pr_issue = source.get("issue", {})
            if "pull_request" in pr_issue and isinstance(pr_issue.get("number"), int):
                numbers.append(pr_issue["number"])
        return tuple(dict.fromkeys(numbers))

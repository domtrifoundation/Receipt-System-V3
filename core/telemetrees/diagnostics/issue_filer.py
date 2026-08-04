"""The real, write-capable half of GitHub issue reporting — creating a new issue,
GitHub-App-authenticated, per `v3-plan-01-core-apis.md` #27's own resolved design.
Deliberately separate from `github_status_client.py` (read-only, unauthenticated): filing
needs a real installation token this codebase has no way to fabricate, and the two
operations have entirely different trust/credential requirements.

**Configuration lives at `<install_root>/telemetrees/github_app.json`** — "the same
top-level, outside-every-release-clone config location already established for other
secrets," per the plan's own words, via `common/local_config_store.LocalConfigStore`.
Never committed, never inside a release clone. `is_configured()` is the honest
"DOMTRI's own canonical instances have this wired up by default; any other install must
explicitly opt in" gate the plan requires — an unconfigured install files nothing, ever.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from common.local_config_store import LocalConfigStore

from .github_app_auth import mint_installation_token

__all__ = ["FileIssueResult", "GitHubAppIssueFilingClient"]

RELPATH = "telemetrees/github_app.json"


@dataclass(frozen=True)
class FileIssueResult:
    ok: bool
    issue_number: int = 0
    url: str = ""
    error_detail: str = ""


class GitHubAppIssueFilingClient:
    def __init__(self, install_root: Path | str) -> None:
        self._store = LocalConfigStore(install_root, RELPATH)

    def is_configured(self) -> bool:
        config = self._store.get_all()
        return bool(config.get("app_id") and config.get("private_key_pem") and config.get("installation_id") and config.get("repo_owner") and config.get("repo_name"))

    async def file_issue(self, title: str, body: str) -> FileIssueResult:
        """Never raises — an unconfigured install, an auth failure, or a GitHub API
        error are all a real `FileIssueResult(ok=False, ...)`, matching this project's
        own errors-are-data discipline even across this real external-network boundary."""
        config = self._store.get_all()
        if not self.is_configured():
            return FileIssueResult(ok=False, error_detail="GitHub App not configured for this install — opt-in required")

        try:
            token = await mint_installation_token(
                config["app_id"], config["private_key_pem"].encode("utf-8"), config["installation_id"],
            )
        except httpx.HTTPError as exc:
            return FileIssueResult(ok=False, error_detail=f"GitHub App auth failed: {exc}")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"https://api.github.com/repos/{config['repo_owner']}/{config['repo_name']}/issues",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    json={"title": title, "body": body},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            return FileIssueResult(ok=False, error_detail=f"GitHub issue creation failed: {exc}")

        return FileIssueResult(ok=True, issue_number=data["number"], url=data["html_url"])

"""Contracts for a genuinely different thing than `dependencies_warden/`'s own tracked
upstream issues: **issues this install has itself filed against this project's own
repository**, when `settings.telemetrees_opt_in` is on and Telemetrees "compiles
diagnosed errors and degradation signals into tracked issues"
(`services/interface/tui/menu_data/settings.py`'s own tooltip for that setting).

**What this module is and is not, stated plainly (`docs/PRINCIPLES.md`'s "never
plausible-looking data" applied to a whole feature, not just one field)**: this is the
real, tested *ledger and live-status* half of that feature — recording what was filed and
checking its current GitHub state. The *detector* half — deciding a diagnosed error is
worth filing, deduplicating by fingerprint, and actually calling GitHub's App-authenticated
issue-creation API — does not exist yet anywhere in this codebase. `record_filed_issue()`
is the real seam that detector would call once built; nothing here fabricates a filing
that didn't happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

__all__ = ["FiledIssueRecord", "IssueStatus", "utcnow"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FiledIssueRecord:
    """One issue this install has filed, as recorded at filing time — never mutated
    afterward. Live state (open/closed, linked PRs) is fetched fresh from GitHub each
    time via `IssueStatus`, never cached into this record, so it can never go stale in a
    way that looks current."""

    fingerprint: str
    """Whatever the (future) detector used to dedupe this diagnosis — opaque here."""
    issue_number: int
    url: str
    title: str
    filed_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class IssueStatus:
    """A live read of one issue's real current GitHub state — `checked_at` is the whole
    point of this being a separate type from `FiledIssueRecord`, since "as of when" is a
    real, load-bearing fact for a status field the operator might be looking at minutes
    or days after it was last refreshed."""

    issue_number: int
    state: str
    """`"open"` | `"closed"` — GitHub's own vocabulary, passed through unchanged."""
    title: str
    url: str
    linked_pr_numbers: tuple[int, ...] = ()
    checked_at: datetime = field(default_factory=utcnow)
    error_detail: str = ""
    """Non-empty when the live GitHub lookup itself failed (rate limit, network, issue
    deleted) — the caller shows this rather than a stale or fabricated state."""

    @property
    def ok(self) -> bool:
        return not self.error_detail

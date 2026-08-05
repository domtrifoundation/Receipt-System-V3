"""Turning a fact change into something a developer will actually read (§4, §9).

§4 states the point bluntly: "Tracking that never reaches anyone is pointless." So this module
converts `FactChange` values into `ChangelogEntry` lines, and `changelog_surface.py` writes
them to `docs/CHANGELOG.md`.

§9 resolved both halves of how:

* **Format and location** — `docs/CHANGELOG.md`, Keep a Changelog, "the standard,
  well-established convention rather than a bespoke format".
* **One write path** — "the same event that already triggers Telemetrees' own internal
  tracking update also appends the human-readable entry, one write path rather than two things
  to keep in sync manually."

§4 also explains *why* a file rather than a dashboard, and the reasoning is specific to this
project: the natural place for a change to land is "a Claude Code session's own context ... a
checked-in, regularly-updated summary file", because this project's development model leans on
LLM-assisted sessions picking up exactly this kind of "here's what changed since you last
worked on this" signal. A dashboard someone has to remember to open would not be read.

**A first observation is not news.** On a fresh install every tracked fact would otherwise
produce a changelog line, and the resulting fourteen-entry dump would bury the one real change
in the next cycle. `entries_for` filters to actual changes for that reason.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..contracts import ChangelogEntry, FactChange, TrackedFactKind

#: Keep a Changelog's own categories, mapped from what kind of fact moved. `Security` for a
#: stale-definitions change is the one worth noticing: a virus-definition database going out of
#: date is a security fact, not a routine version bump, and filing it under `Changed` would let
#: it scroll past unread among ordinary dependency churn.
_CATEGORY_BY_KIND = {
    TrackedFactKind.RELEASE_VERSION: "Changed",
    TrackedFactKind.FREE_THREADING_SUPPORT: "Added",
    TrackedFactKind.UPSTREAM_ISSUE_STATUS: "Fixed",
    TrackedFactKind.MODEL_CURRENCY: "Changed",
    TrackedFactKind.DATASET_FRESHNESS: "Security",
    TrackedFactKind.REGULATORY_VALUE: "Changed",
}


def category_for(kind: TrackedFactKind) -> str:
    """Keep a Changelog category for a fact kind, defaulting to `Changed`.

    A default rather than a raise: a fact kind added later without a mapping should still reach
    the changelog under a plausible heading, since the alternative is the new kind silently
    never being surfaced — which is the one outcome §4 says makes tracking pointless.
    """
    return _CATEGORY_BY_KIND.get(kind, "Changed")


def describe(change: FactChange) -> str:
    """One human-readable line for a change.

    Phrased per fact kind rather than generically, because "opencv-python: open -> closed" is
    close to meaningless while "the tracked blocker opencv/opencv#27933 is now closed" is
    immediately actionable — and an actionable line is the entire deliverable of this module.
    """
    fact = change.fact
    if fact.kind is TrackedFactKind.UPSTREAM_ISSUE_STATUS:
        return (
            f"{fact.dependency}: tracked upstream issue {fact.detail} is now {fact.value} "
            f"(was {change.previous})"
        )
    if fact.kind is TrackedFactKind.FREE_THREADING_SUPPORT:
        return (
            f"{fact.dependency}: free-threading support is now {fact.value} "
            f"(was {change.previous})"
        )
    if fact.kind is TrackedFactKind.DATASET_FRESHNESS:
        return f"{fact.dependency}: dataset version changed to {fact.value} (was {change.previous})"
    if fact.kind is TrackedFactKind.REGULATORY_VALUE:
        return (
            f"{fact.dependency}: tracked regulatory value changed to {fact.value} "
            f"(was {change.previous}) — check any export logic that depends on it"
        )
    if fact.kind is TrackedFactKind.MODEL_CURRENCY:
        return (
            f"{fact.dependency}: upstream model generation is now {fact.value} "
            f"(vendored copy was tracking {change.previous})"
        )
    return f"{fact.dependency}: {change.previous} -> {fact.value}"


def entries_for(changes: Sequence[FactChange]) -> tuple[ChangelogEntry, ...]:
    """Changelog entries for the changes that are genuinely changes.

    First observations are dropped here rather than at the call site so every consumer gets the
    same answer — a second filter written slightly differently elsewhere is exactly how a fresh
    install ends up dumping its whole inventory into the changelog.
    """
    return tuple(
        ChangelogEntry(
            category=category_for(change.fact.kind),
            text=describe(change),
            recorded_at=change.fact.observed_at,
        )
        for change in changes
        if change.changed
    )


__all__ = ["category_for", "describe", "entries_for"]

"""Telemetrees data contracts (`v3-deepdive-28-telemetrees-api.md` §3, §6).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). It is the only file in this
package that anything outside `core/telemetrees/` imports from; Dependencies Warden's own
`contracts.py` re-exports from here rather than defining a parallel set, exactly as its §2
layout says.

The load-bearing idea is `TrackedFactKind`, and §1's own boundary states it as a design
requirement rather than a nicety: **this API does not track every dependency uniformly.** A
plain release-version poller would never surface "the free-threaded-wheel blocker is still
open", because that fact lives on a GitHub issue rather than in a release feed and can resolve
either with or without a version bump (§3.2). One dependency genuinely needs several kinds of
fact watched at once, which is why `TrackedDependency.fact_kinds` is a tuple rather than a
single value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from common.frozen_dict import FrozenDict

#: §9's locked-in polling cadence. Daily is a sensible starting point for facts that move as
#: slowly as dependency releases and upstream issue resolution; real data can tune it.
DEFAULT_POLL_INTERVAL_HOURS: int = 24

#: §9's resolved surfacing target: the standard Keep a Changelog convention rather than a
#: bespoke format, written by the same event that updates the internal tracking state so
#: there is one write path rather than two things to keep in sync.
CHANGELOG_PATH: str = "docs/CHANGELOG.md"

#: The PyPI trove classifier that is a real, standardized free-threading signal — as opposed
#: to guessing from changelog prose, which the Warden's §8 hook explicitly tests against.
FREE_THREADING_CLASSIFIER: str = "Programming Language :: Python :: Free Threading"

#: §9's resolved community cross-check. A secondary signal, never the only one: a dependency's
#: own classifier is authoritative about what it declares, and this catches the case where a
#: package supports free threading in practice before declaring it.
COMMUNITY_TRACKER_URL: str = "https://py-free-threading.github.io"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TrackedFactKind(str, Enum):
    """What kind of fact is being watched about a dependency (§3).

    The first three are §3's own enum verbatim. The last three close the gap between that enum
    and §3.1's actual inventory, which asks for facts none of the original three can express —
    flagged here rather than quietly forced into `RELEASE_VERSION`:

    * `MODEL_CURRENCY` — "is our vendored copy stale relative to upstream's newer releases",
      §3.1's RapidOCR-versus-PaddleOCR case. Not a release check on a package we install.
    * `DATASET_FRESHNESS` — ClamAV's virus-definition database. §3.1 calls this out as its own
      shape specifically because a stale definitions database is a silent security gap
      distinct from the `pyclamd` package being outdated.
    * `REGULATORY_VALUE` — whether BIR has revised the SLSP threshold values. §3.1 names this
      as "genuinely distinct again", since what changes is a government-set number that moves
      independently of any software release.

    Values are stable wire strings. Adding a member is fine; renaming or reusing a value is a
    breaking change to anything persisting a registration.
    """

    RELEASE_VERSION = "release_version"
    FREE_THREADING_SUPPORT = "free_threading_support"
    UPSTREAM_ISSUE_STATUS = "upstream_issue_status"
    MODEL_CURRENCY = "model_currency"
    DATASET_FRESHNESS = "dataset_freshness"
    REGULATORY_VALUE = "regulatory_value"


class FreeThreadingStatus(str, Enum):
    """What a dependency currently declares about free-threading support.

    `UNKNOWN` is deliberately distinct from `UNSUPPORTED`. A package that has said nothing is
    not the same as one that has said no, and collapsing them would turn "we have not checked"
    into a claim — the same distinction Health's own `ServiceState.UNKNOWN` draws for the same
    reason.
    """

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class IssueState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TrackedDependency:
    """One registered dependency and what is watched about it (§3).

    `fact_kinds` is a tuple because §3's whole point is that one dependency often needs several
    kinds at once — `opencv-python` needs release monitoring *and* a free-threading flag *and*
    two specific upstream issues, and any one of those alone would miss the others.

    `notes` records *why* something is tracked, which matters more than it looks: §3.1 was
    assembled from deferred items scattered across every prior deep-dive, and an entry whose
    reason is lost becomes an entry nobody dares remove and nobody can act on.
    """

    name: str
    fact_kinds: tuple[TrackedFactKind, ...]
    upstream_issue_refs: tuple[str, ...] = ()
    source_deep_dive: str = ""
    notes: str = ""


@dataclass(frozen=True)
class TrackedFact:
    """The last observed value of one fact about one dependency.

    `value` is a string for every kind deliberately: a version, an issue state, a classifier
    verdict and a regulatory threshold have nothing in common structurally, and a union type
    would push a match statement into every consumer for no gain over comparing "what it was"
    to "what it is now" — which is the only operation this API performs on it.
    """

    dependency: str
    kind: TrackedFactKind
    value: str
    observed_at: datetime = field(default_factory=utcnow)
    detail: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        """Identity of the fact, independent of its value.

        `detail` carries the issue ref for issue-status facts, so a dependency tracking two
        separate issues has two distinct facts of the same kind rather than one that flickers
        between them.
        """
        return (self.dependency, self.kind.value, self.detail)


@dataclass(frozen=True)
class ReleaseEvent:
    """A new release observed on PyPI (§3's `RELEASE_VERSION`).

    `is_prerelease` exists because file 02's rule #8 requires watching beta/alpha/RC activity,
    not only stable releases — the entire point of day-0 support is knowing before it ships.
    """

    dependency: str
    version: str
    is_prerelease: bool = False
    released_at: datetime | None = None
    changelog_url: str = ""


@dataclass(frozen=True)
class IssueStateEvent:
    """A tracked upstream issue's state (§3.2)."""

    dependency: str
    issue_ref: str
    state: IssueState
    title: str = ""
    url: str = ""


@dataclass(frozen=True)
class FreeThreadingStatusEvent:
    """A dependency's declared free-threading support (§3.1, Warden §3).

    `source` records which signal produced it — the trove classifier, the community tracker,
    or nothing. Warden's §8 hook tests specifically that the classifier is *read* where present
    rather than guessed at from changelog text, and that is only checkable if the answer says
    where it came from.
    """

    dependency: str
    status: FreeThreadingStatus
    source: str = ""
    detail: str = ""


@dataclass(frozen=True)
class FactChange:
    """One tracked fact moving from one value to another — what §4 exists to surface.

    A change with `previous=None` is a first observation, not a change, and is reported as such
    rather than as "it changed from nothing": on first run every fact would otherwise look like
    news, burying the one thing that actually moved.
    """

    fact: TrackedFact
    previous: str | None = None

    @property
    def is_first_observation(self) -> bool:
        return self.previous is None

    @property
    def changed(self) -> bool:
        return self.previous is not None and self.previous != self.fact.value


@dataclass(frozen=True)
class ChangelogEntry:
    """One line destined for `docs/CHANGELOG.md` (§9).

    Keep a Changelog's own categories rather than invented ones — `Added`, `Changed`, `Fixed`,
    `Security` — because §9 resolved the format as the standard convention specifically to
    avoid a bespoke one.
    """

    category: str
    text: str
    recorded_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class PollResult:
    """The outcome of one polling pass (§5).

    Errors are data (`docs/PRINCIPLES.md` §4.1): a poller that could not reach PyPI reports
    that here and the pass continues with whatever else it could reach. Monitoring that fails
    closed would mean one unreachable registry silently stopping every other dependency's
    tracking — the opposite of what a monitoring system is for.
    """

    changes: tuple[FactChange, ...] = ()
    unreachable: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    polled_at: datetime = field(default_factory=utcnow)

    @property
    def real_changes(self) -> tuple[FactChange, ...]:
        return tuple(c for c in self.changes if c.changed)


@dataclass(frozen=True)
class TelemetreesMetrics:
    """This API's own counters, snapshotted (`metrics.py`)."""

    polls_attempted: int = 0
    polls_unreachable: int = 0
    facts_observed: int = 0
    facts_changed: int = 0
    changelog_entries_written: int = 0
    issue_state_changes_detected: int = 0


__all__ = [
    "CHANGELOG_PATH",
    "COMMUNITY_TRACKER_URL",
    "DEFAULT_POLL_INTERVAL_HOURS",
    "FREE_THREADING_CLASSIFIER",
    "ChangelogEntry",
    "FactChange",
    "FreeThreadingStatus",
    "FreeThreadingStatusEvent",
    "IssueState",
    "IssueStateEvent",
    "PollResult",
    "ReleaseEvent",
    "TelemetreesMetrics",
    "TrackedDependency",
    "TrackedFact",
    "TrackedFactKind",
    "utcnow",
]

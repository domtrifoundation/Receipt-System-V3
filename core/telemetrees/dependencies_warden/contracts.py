"""Dependencies Warden's contracts — re-exported from the parent (§2).

Warden's own §2 layout says "re-exported from parent", and this file is exactly that and
nothing more. Defining a parallel set here would give the sub-API its own quietly diverging
opinion about what a `TrackedFact` is, which is precisely the drift `docs/PRINCIPLES.md` §1.1
avoids by making `contracts.py` the single import surface.

`TelemetreesError` and the poller-facing error types stay in the parent's `errors.py` for the
same reason; this package's own `errors.py` adds only what is genuinely Warden-specific.
"""

from __future__ import annotations

from ..contracts import (
    COMMUNITY_TRACKER_URL,
    FREE_THREADING_CLASSIFIER,
    FactChange,
    FreeThreadingStatus,
    FreeThreadingStatusEvent,
    IssueState,
    IssueStateEvent,
    PollResult,
    ReleaseEvent,
    TrackedDependency,
    TrackedFact,
    TrackedFactKind,
    utcnow,
)

__all__ = [
    "COMMUNITY_TRACKER_URL",
    "FREE_THREADING_CLASSIFIER",
    "FactChange",
    "FreeThreadingStatus",
    "FreeThreadingStatusEvent",
    "IssueState",
    "IssueStateEvent",
    "PollResult",
    "ReleaseEvent",
    "TrackedDependency",
    "TrackedFact",
    "TrackedFactKind",
    "utcnow",
]

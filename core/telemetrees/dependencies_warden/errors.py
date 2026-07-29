"""Warden-specific errors, on top of the parent's taxonomy.

Deliberately thin. Everything about how this package treats failure — degrade, never fail
closed, and never report a fact that was not observed — is stated in `core/telemetrees/errors.py`
and applies here unchanged. Only what is genuinely specific to polling lives in this file.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..errors import TelemetreesError


class NoPollerForFactKind(TelemetreesError):
    """A dependency declares a fact kind nothing knows how to poll.

    This is the failure Warden §8's multi-poller coverage test exists to catch *before* it
    reaches production: a declared kind with no poller behind it is a fact nobody is actually
    watching, and it looks identical to a healthy registration from the outside.
    """


class PollerAlreadyRegistered(TelemetreesError):
    """Two pollers claiming the same fact kind.

    Rejected rather than last-one-wins: which poller answers a kind would otherwise depend on
    import order, and the two would disagree exactly where it mattered.
    """


ERROR_CODES: FrozenDict = FrozenDict(
    {
        NoPollerForFactKind: "NO_POLLER_FOR_FACT_KIND",
        PollerAlreadyRegistered: "POLLER_ALREADY_REGISTERED",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "NO_POLLER_FOR_FACT_KIND": "Nothing is registered to poll that kind of fact.",
        "POLLER_ALREADY_REGISTERED": "A poller is already registered for that fact kind.",
    }
)


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "NoPollerForFactKind",
    "PollerAlreadyRegistered",
]

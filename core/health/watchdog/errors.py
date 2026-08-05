"""Watchdog error taxonomy.

Surfaced as `error_code`/`error_detail` on the result contracts rather than raised across the
API boundary (`docs/PRINCIPLES.md` §4.1). The set is small because Watchdog's surface is small
— two RPCs (§7) over one binary question.

Nothing here is fatal to a kick. A malformed heartbeat is rejected and counted; it never takes
down the receiving loop, because a Watchdog that can be crashed by a bad kick is a Watchdog
that a genuinely sick service can silence just by sending garbage — which inverts the entire
point of the mechanism.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class WatchdogError(Exception):
    """Base for everything this sub-API raises internally, never across its boundary."""


class InvalidHeartbeat(WatchdogError):
    """A kick with an empty service name or instance id.

    Rejected rather than recorded: a heartbeat that cannot be attributed to an instance
    proves nothing about any instance's liveness, and recording it under a blank key would
    let one malformed sender vouch for a service that is actually silent.
    """


class UnknownInstance(WatchdogError):
    """A query about a service instance that has never kicked.

    Resolves to `Liveness.UNSEEN` on the read path — a real answer, not a failure. This type
    exists for the case where a caller asked about an instance by id and wants to be told the
    id itself is unrecognised rather than handed a state record for something that has never
    existed.
    """


#: Stable wire codes for the `.proto` surface (§7). Field-only-append discipline applies: a
#: code is added, never renamed, because a client may be matching on it.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        InvalidHeartbeat: "INVALID_HEARTBEAT",
        UnknownInstance: "UNKNOWN_INSTANCE",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "INVALID_HEARTBEAT": "The heartbeat named no service or no instance.",
        "UNKNOWN_INSTANCE": "No heartbeat has ever been received from that instance.",
        "INTERNAL": "An unmapped internal error.",
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped."""
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    return ERROR_SUMMARIES.get(code, ERROR_SUMMARIES["INTERNAL"])


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "InvalidHeartbeat",
    "UnknownInstance",
    "WatchdogError",
    "code_for",
    "summary_for",
]

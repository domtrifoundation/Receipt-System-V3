"""Support Ticketing error taxonomy.

Surfaced as `error_code`/`error_detail` on the result contracts rather than raised across the
boundary (`docs/PRINCIPLES.md` §4.1).

The posture here is ordinary: fail closed on the permission checks (§4.2), degrade gracefully
everywhere else (§4.4). Nothing in a support conversation is worth taking a caller down for —
but who may act on a ticket is a real access decision, and an unresolvable session denies.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class SupportTicketingError(Exception):
    """Base for everything this API raises internally, never across its boundary."""


class UnknownTicket(SupportTicketingError):
    """An operation naming a ticket id nothing has recorded."""


class InvalidTicketRequest(SupportTicketingError):
    """An empty subject, an empty message body, an empty creator.

    An empty subject is rejected rather than defaulted to something like "(no subject)": a
    staff queue where several rows share a placeholder title is a queue nobody can triage.
    """


class InvalidStatusTransition(SupportTicketingError):
    """A move the lifecycle does not permit — reopening a closed ticket, most often.

    Refused explicitly rather than silently ignored: a silent no-op returns success to someone
    whose action did nothing, which in a support context means a user believing staff were
    told something they never were.
    """


class RoleForbidden(SupportTicketingError):
    """The caller's resolved role does not permit this action.

    Resolved server-side from the session, never from a role the caller asserts about itself
    (§4.2). An unresolvable session lands here too — a caller cannot tell "Auth is down" from
    "you may not do this", and neither should the decision.
    """


class TicketAccessDenied(SupportTicketingError):
    """A user reaching a ticket that is not theirs.

    Support conversations routinely contain receipt details, amounts and vendor names, so a
    ticket is per-user data in the same sense a receipt is.
    """


ERROR_CODES: FrozenDict = FrozenDict(
    {
        UnknownTicket: "UNKNOWN_TICKET",
        InvalidTicketRequest: "INVALID_TICKET_REQUEST",
        InvalidStatusTransition: "INVALID_STATUS_TRANSITION",
        RoleForbidden: "ROLE_FORBIDDEN",
        TicketAccessDenied: "TICKET_ACCESS_DENIED",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "UNKNOWN_TICKET": "No ticket exists with that id.",
        "INVALID_TICKET_REQUEST": "The ticket request was missing a required field.",
        "INVALID_STATUS_TRANSITION": "That status change is not permitted from the current state.",
        "ROLE_FORBIDDEN": "The caller's role does not permit that action.",
        "TICKET_ACCESS_DENIED": "That ticket belongs to another user.",
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
    "InvalidStatusTransition",
    "InvalidTicketRequest",
    "RoleForbidden",
    "SupportTicketingError",
    "TicketAccessDenied",
    "UnknownTicket",
    "code_for",
    "summary_for",
]

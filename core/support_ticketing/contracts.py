"""Support Ticketing data contracts (`v3-deepdive-52-support-ticketing.md` §3, §7, §9).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). It is the only file in this
package that anything outside `core/support_ticketing/` imports from.

`Ticket.related_receipt_id` is §3's own emphasis, not an afterthought: "given how many support
questions in this specific domain are genuinely about one receipt ('why did this get flagged,'
'this vendor match looks wrong')". A ticket that names a receipt lets staff jump straight to
that receipt's detail screen and its Historian narrative instead of asking the user to describe
what they are looking at — which is §8's own receipt-context-jump hook.

`TICKET_ID_PREFIX` is load-bearing rather than cosmetic. §8's break-glass hook wants a grant's
free-text `reason` that happens to name a ticket to resolve to a real `Ticket` — and that is
only possible if a ticket id is recognisable inside prose. A bare UUID in a sentence is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from common.frozen_dict import FrozenDict

#: §9's resolved auto-close window: "a resolved ticket with no further activity for two weeks
#: auto-closes rather than sitting open indefinitely."
AUTO_CLOSE_AFTER = timedelta(days=14)

#: The prefix every ticket id carries. See the module docstring — §8's break-glass hook depends
#: on an id being findable inside free text, which a bare UUID is not.
TICKET_ID_PREFIX = "TKT-"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TicketStatus(str, Enum):
    """§2's lifecycle: open → in_progress → resolved → closed.

    `RESOLVED` and `CLOSED` are separate states rather than one terminal state, and the
    distinction is what §9's auto-close rule operates on: resolved means staff believe they are
    done and the user still has two weeks to say otherwise; closed means that window passed or
    someone closed it deliberately. Collapsing them would remove the window entirely.

    Values are stable wire strings. Adding a member is fine; renaming or reusing one is a
    breaking change to the `.proto` surface.
    """

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class AuthorKind(str, Enum):
    """Who wrote a message. §3's own `author` field is `"user" | "staff:<user_id>"`.

    Split into a kind plus an id rather than kept as one encoded string: parsing a role back
    out of a formatted string at every read is how a display bug becomes a permissions bug, and
    the wire format can still render §3's shape from these two fields.
    """

    USER = "user"
    STAFF = "staff"


#: §2's state machine as a lookup table — the single source of truth `lifecycle.py` reads
#: rather than restating. `FrozenDict` per §2.1.1.
#:
#: `RESOLVED -> IN_PROGRESS` is deliberately allowed: a user replying "that didn't fix it" to a
#: resolved ticket is the ordinary case, and forcing them to open a second ticket would lose
#: the conversation that explains the problem. `CLOSED` is genuinely terminal.
VALID_TRANSITIONS: FrozenDict = FrozenDict(
    {
        TicketStatus.OPEN: frozenset({TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CLOSED}),
        TicketStatus.IN_PROGRESS: frozenset({TicketStatus.RESOLVED, TicketStatus.CLOSED}),
        TicketStatus.RESOLVED: frozenset({TicketStatus.IN_PROGRESS, TicketStatus.CLOSED}),
        TicketStatus.CLOSED: frozenset(),
    }
)


@dataclass(frozen=True)
class Ticket:
    """One support ticket (§3).

    `assigned_to` is `None` for an unassigned ticket, which §4 makes the normal starting state:
    "an unassigned ticket is visible to any staff member, any staff member can self-assign".
    """

    ticket_id: str
    created_by: str
    subject: str
    status: TicketStatus = TicketStatus.OPEN
    assigned_to: str | None = None
    related_receipt_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    @property
    def is_terminal(self) -> bool:
        return self.status is TicketStatus.CLOSED

    @property
    def links_a_receipt(self) -> bool:
        """§8's receipt-context-jump hook rests on this being answerable from the ticket."""
        return bool(self.related_receipt_id)


@dataclass(frozen=True)
class TicketMessage:
    """One message in a ticket's conversation (§3)."""

    ticket_id: str
    author_kind: AuthorKind
    author_user_id: str
    body: str
    posted_at: datetime = field(default_factory=utcnow)

    @property
    def author(self) -> str:
        """§3's own wire shape: `"user"` or `"staff:<user_id>"`.

        Derived rather than stored, so it cannot disagree with the two fields it renders.
        """
        if self.author_kind is AuthorKind.STAFF:
            return f"staff:{self.author_user_id}"
        return "user"


@dataclass(frozen=True)
class TicketResult:
    """The outcome of any single-ticket operation.

    Errors are data (`docs/PRINCIPLES.md` §4.1). `ticket` is `None` on failure rather than a
    partially-populated record, so a caller cannot accidentally act on a ticket that was not
    actually changed.
    """

    ticket: Ticket | None = None
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.ticket is not None and not self.error_code


@dataclass(frozen=True)
class MessageResult:
    message: TicketMessage | None = None
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.message is not None and not self.error_code


@dataclass(frozen=True)
class TicketListQuery:
    """§7's `ListTickets` filter.

    `unassigned_only` exists because §4's shared-queue model makes "what can I pick up" the
    single most common staff question, and deriving it from `assigned_to=None` would be
    ambiguous with "do not filter on assignment at all".
    """

    statuses: tuple[TicketStatus, ...] = ()
    created_by: str | None = None
    assigned_to: str | None = None
    unassigned_only: bool = False
    related_receipt_id: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class TicketListResult:
    tickets: tuple[Ticket, ...] = ()
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code


@dataclass(frozen=True)
class SupportTicketingMetrics:
    """This API's own counters, snapshotted (`metrics.py`)."""

    tickets_created: int = 0
    messages_posted: int = 0
    tickets_assigned: int = 0
    tickets_reassigned: int = 0
    tickets_resolved: int = 0
    tickets_closed: int = 0
    tickets_reopened: int = 0
    tickets_auto_closed: int = 0
    invalid_transitions_rejected: int = 0
    actions_denied_role: int = 0
    actions_denied_ownership: int = 0
    break_glass_refs_resolved: int = 0
    break_glass_refs_unresolvable: int = 0


__all__ = [
    "AUTO_CLOSE_AFTER",
    "TICKET_ID_PREFIX",
    "VALID_TRANSITIONS",
    "AuthorKind",
    "MessageResult",
    "SupportTicketingMetrics",
    "Ticket",
    "TicketListQuery",
    "TicketListResult",
    "TicketMessage",
    "TicketResult",
    "TicketStatus",
    "utcnow",
]

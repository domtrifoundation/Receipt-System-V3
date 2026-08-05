"""The ticket lifecycle: open → in_progress → resolved → closed (§2, §8, §9).

An in-memory-plus-injected-store surface over the state machine `contracts.VALID_TRANSITIONS`
defines. Everything that decides *who may act* lives in `assignment.py`; everything that decides
*what state may follow* is the table in `contracts.py`. This module composes the two and owns
neither, which is what keeps either one changeable without re-reading this file.

Three behaviours here are worth stating because each closes a specific way support software
goes wrong:

* **`resolve_break_glass_reference` (§8's first hook).** Auth's break-glass `reason` is free
  text, and §1 is clear this API must not make a formal ticket mandatory for a grant. So the
  link is a *resolution* rather than a constraint: a reason mentioning `TKT-…` resolves to a
  real ticket if one exists, and to nothing if it does not — no grant is ever refused for
  lacking one. §8 wants this tested precisely because "the two could silently drift apart".
* **`receipt_context_for` (§8's second hook).** A ticket carrying `related_receipt_id` gives
  staff a deep link to that receipt rather than asking the user to describe what they are
  looking at. Returning the target rather than rendering it keeps this API out of the
  presentation business (§1's boundary).
* **`auto_close_stale` (§9).** A resolved ticket with no activity for fourteen days closes.
  Resolved and closed are separate states precisely so that window exists; auto-closing from
  `OPEN` would shut tickets nobody ever answered, which is the opposite of the intent.

**Notifications are not sent from here** (§1): this API owns ticket state and conversation
content, not how a user gets told. `TicketStore` reports what changed and something else
decides whether that is worth a notification.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from .assignment import (
    authorize_assignment,
    authorize_status_change,
    is_staff,
    may_post,
    may_view,
)
from .contracts import (
    AUTO_CLOSE_AFTER,
    TICKET_ID_PREFIX,
    VALID_TRANSITIONS,
    AuthorKind,
    MessageResult,
    Ticket,
    TicketListQuery,
    TicketListResult,
    TicketMessage,
    TicketResult,
    TicketStatus,
    utcnow,
)
from .errors import (
    InvalidStatusTransition,
    InvalidTicketRequest,
    RoleForbidden,
    SupportTicketingError,
    TicketAccessDenied,
    UnknownTicket,
    code_for,
)
from .metrics import SupportTicketingMetricsCollector

#: Resolves a session id to `(user_id, role)`, or `None` for a session it cannot vouch for.
#: The same seam shape every other package in this repo uses onto Auth (`docs/PRINCIPLES.md`
#: §1.3), with the same rule: `None` denies, never permits.
SessionResolver = Callable[[str], "tuple[str, str] | None"]


def deny_all_sessions(session_id: str) -> None:
    """The safe default resolver. Denies every session.

    A process that forgets to wire Auth in gets a closed door rather than an open one
    (`docs/PRINCIPLES.md` §4.2), matching `core/audit/service.py`'s own `deny_all_roles`.
    """
    return None


def new_ticket_id() -> str:
    """A prefixed UUID4.

    The prefix is not decoration — §8's break-glass hook needs a ticket id to be *findable
    inside free text*, and a bare UUID in a sentence is not. UUID rather than a sequence number
    for the same reason `core/audit/writer.py` gives: a guessable id makes a ticket's existence
    trivially probeable.
    """
    return f"{TICKET_ID_PREFIX}{uuid.uuid4().hex[:12].upper()}"


def can_transition(current: TicketStatus, target: TicketStatus) -> bool:
    """Whether the lifecycle permits `current` → `target`.

    Reads `VALID_TRANSITIONS` rather than restating it — two opinions about which edges are
    legal would disagree exactly at the edge that mattered.
    """
    return target in VALID_TRANSITIONS.get(current, frozenset())


class TicketStore:
    """The whole lifecycle surface: create, post, assign, transition, list (§7).

    Holds tickets and messages in memory behind a real lock. §6 classifies this API as thin
    CRUD over its own small database; the persistence adapter is a later wiring step, and the
    lock is real rather than a GIL assumption because this project targets free-threaded 3.14t
    (`docs/PRINCIPLES.md` §3.3.1).
    """

    def __init__(
        self,
        *,
        sessions: SessionResolver = deny_all_sessions,
        metrics: SupportTicketingMetricsCollector | None = None,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sessions = sessions
        self._metrics = metrics or SupportTicketingMetricsCollector()
        self._now = now
        self._lock = threading.Lock()
        self._tickets: dict[str, Ticket] = {}
        self._messages: dict[str, list[TicketMessage]] = {}

    @property
    def metrics(self) -> SupportTicketingMetricsCollector:
        return self._metrics

    # ------------------------------------------------------------------------ session

    def _resolve(self, session_id: str) -> tuple[str, str]:
        """Who is calling, from the session — never from anything the caller asserts (§4.2)."""
        try:
            resolved = self._sessions(session_id)
        except Exception:  # noqa: BLE001 - an unreachable Auth denies, never permits
            resolved = None
        if resolved is None:
            raise RoleForbidden("session could not be resolved")
        return resolved

    def _require(self, ticket_id: str) -> Ticket:
        with self._lock:
            found = self._tickets.get(ticket_id)
        if found is None:
            raise UnknownTicket(ticket_id)
        return found

    # ------------------------------------------------------------------------- create

    def create_ticket(
        self,
        session_id: str,
        subject: str,
        *,
        body: str = "",
        related_receipt_id: str | None = None,
    ) -> TicketResult:
        """Open a ticket as the session's own user."""
        try:
            actor, _role = self._resolve(session_id)
            if not subject.strip():
                raise InvalidTicketRequest("a ticket needs a subject")
        except SupportTicketingError as exc:
            self._metrics.increment(
                "actions_denied_role" if isinstance(exc, RoleForbidden) else "tickets_created", 0
            )
            return TicketResult(error_code=code_for(exc), error_detail=str(exc))

        now = self._now()
        ticket = Ticket(
            ticket_id=new_ticket_id(),
            created_by=actor,
            subject=subject.strip(),
            status=TicketStatus.OPEN,
            related_receipt_id=related_receipt_id,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._tickets[ticket.ticket_id] = ticket
            self._messages[ticket.ticket_id] = []
        self._metrics.increment("tickets_created")

        if body.strip():
            self.post_message(session_id, ticket.ticket_id, body)
        return TicketResult(ticket=ticket)

    # ------------------------------------------------------------------------ message

    def post_message(self, session_id: str, ticket_id: str, body: str) -> MessageResult:
        try:
            actor, role = self._resolve(session_id)
            ticket = self._require(ticket_id)
            if not body.strip():
                raise InvalidTicketRequest("a message needs a body")
            if not may_post(ticket, actor, role):
                raise TicketAccessDenied(ticket_id)
        except SupportTicketingError as exc:
            if isinstance(exc, (RoleForbidden, TicketAccessDenied)):
                self._metrics.increment("actions_denied_ownership")
            return MessageResult(error_code=code_for(exc), error_detail=str(exc))

        message = TicketMessage(
            ticket_id=ticket_id,
            author_kind=AuthorKind.STAFF if is_staff(role) else AuthorKind.USER,
            author_user_id=actor,
            body=body.strip(),
            posted_at=self._now(),
        )
        with self._lock:
            self._messages.setdefault(ticket_id, []).append(message)
            self._tickets[ticket_id] = self._touch(self._tickets[ticket_id])
        self._metrics.increment("messages_posted")
        return MessageResult(message=message)

    def messages_for(self, session_id: str, ticket_id: str) -> tuple[TicketMessage, ...]:
        """The conversation, gated the same way posting to it is.

        Raises rather than returning empty for a denied read: an empty conversation and a
        forbidden one are different facts, and returning `()` for both would let a caller show
        "no messages yet" for someone else's ticket.
        """
        actor, role = self._resolve(session_id)
        ticket = self._require(ticket_id)
        if not may_view(ticket, actor, role):
            raise TicketAccessDenied(ticket_id)
        with self._lock:
            return tuple(self._messages.get(ticket_id, ()))

    # ------------------------------------------------------------------------ assign

    def assign_ticket(self, session_id: str, ticket_id: str, assignee_user_id: str) -> TicketResult:
        """§4's shared-queue self-assign, with reassignment reserved to an owner."""
        try:
            actor, role = self._resolve(session_id)
            ticket = self._require(ticket_id)
            authorize_assignment(ticket, actor, role, assignee_user_id)
        except SupportTicketingError as exc:
            self._metrics.increment("actions_denied_role")
            return TicketResult(error_code=code_for(exc), error_detail=str(exc))

        reassignment = ticket.assigned_to not in (None, assignee_user_id)
        updated = self._replace(
            ticket,
            assigned_to=assignee_user_id,
            status=(
                TicketStatus.IN_PROGRESS
                if ticket.status is TicketStatus.OPEN
                else ticket.status
            ),
        )
        with self._lock:
            self._tickets[ticket_id] = updated
        self._metrics.increment("tickets_reassigned" if reassignment else "tickets_assigned")
        return TicketResult(ticket=updated)

    # ------------------------------------------------------------------- status moves

    def set_status(self, session_id: str, ticket_id: str, target: TicketStatus) -> TicketResult:
        try:
            actor, role = self._resolve(session_id)
            ticket = self._require(ticket_id)
            authorize_status_change(ticket, actor, role)
            if not can_transition(ticket.status, target):
                raise InvalidStatusTransition(
                    f"{ticket.status.value} -> {target.value} is not a permitted move"
                )
        except SupportTicketingError as exc:
            if isinstance(exc, InvalidStatusTransition):
                self._metrics.increment("invalid_transitions_rejected")
            else:
                self._metrics.increment("actions_denied_role")
            return TicketResult(error_code=code_for(exc), error_detail=str(exc))

        updated = self._replace(ticket, status=target)
        with self._lock:
            self._tickets[ticket_id] = updated
        if target is TicketStatus.RESOLVED:
            self._metrics.increment("tickets_resolved")
        elif target is TicketStatus.CLOSED:
            self._metrics.increment("tickets_closed")
        elif target is TicketStatus.IN_PROGRESS and ticket.status is TicketStatus.RESOLVED:
            self._metrics.increment("tickets_reopened")
        return TicketResult(ticket=updated)

    # --------------------------------------------------------------------------- list

    def list_tickets(self, session_id: str, query: TicketListQuery) -> TicketListResult:
        """§7's `ListTickets`, scoped to what the caller may actually see.

        A client's listing is silently narrowed to their own tickets rather than refused: a
        user asking for "my tickets" and a user asking for "all tickets" both legitimately mean
        the same thing from their side of the API, and refusing the second would be a confusing
        error for a request that has an obvious correct answer.
        """
        try:
            actor, role = self._resolve(session_id)
        except SupportTicketingError as exc:
            self._metrics.increment("actions_denied_role")
            return TicketListResult(error_code=code_for(exc), error_detail=str(exc))

        with self._lock:
            candidates = list(self._tickets.values())

        if not is_staff(role):
            candidates = [t for t in candidates if t.created_by == actor]
        if query.statuses:
            candidates = [t for t in candidates if t.status in query.statuses]
        if query.created_by:
            candidates = [t for t in candidates if t.created_by == query.created_by]
        if query.unassigned_only:
            candidates = [t for t in candidates if t.assigned_to is None]
        elif query.assigned_to:
            candidates = [t for t in candidates if t.assigned_to == query.assigned_to]
        if query.related_receipt_id:
            candidates = [t for t in candidates if t.related_receipt_id == query.related_receipt_id]

        candidates.sort(key=lambda t: (t.created_at, t.ticket_id))
        return TicketListResult(tickets=tuple(candidates[: max(query.limit, 0)]))

    # ------------------------------------------------------- §8's two integration hooks

    def resolve_break_glass_reference(self, reason: str) -> Ticket | None:
        """§8's break-glass hook: does this grant's free-text reason name a real ticket?

        Resolution, never a requirement. §1 is explicit that break-glass "still just takes a
        free-text reason" and that this API "doesn't require every break-glass grant to have a
        formal ticket behind it" — so a reason naming nothing, or naming a ticket that does not
        exist, returns `None` and no grant is ever refused for it.

        §8 asks for this specifically because "the two could silently drift apart otherwise":
        if ticket ids stopped being findable in prose, every grant would keep working and the
        link would quietly stop resolving, with nothing failing to say so.
        """
        if not reason:
            return None
        upper = reason.upper()
        index = upper.find(TICKET_ID_PREFIX)
        if index < 0:
            self._metrics.increment("break_glass_refs_unresolvable")
            return None
        candidate = ""
        for char in upper[index:]:
            if char.isalnum() or char == "-":
                candidate += char
            else:
                break
        with self._lock:
            found = self._tickets.get(candidate)
        self._metrics.increment(
            "break_glass_refs_resolved" if found else "break_glass_refs_unresolvable"
        )
        return found

    def receipt_context_for(self, session_id: str, ticket_id: str) -> str | None:
        """§8's receipt-context hook: which receipt should staff be deep-linked to, if any.

        Returns the receipt id rather than a rendered link, because this API owns ticket state
        and not presentation (§1) — the TUI and the webapp each build their own destination
        from it, and neither has to agree with the other about URL shape.
        """
        actor, role = self._resolve(session_id)
        ticket = self._require(ticket_id)
        if not may_view(ticket, actor, role):
            raise TicketAccessDenied(ticket_id)
        return ticket.related_receipt_id

    # -------------------------------------------------------------- §9's auto-close

    def auto_close_stale(self, *, after: timedelta = AUTO_CLOSE_AFTER) -> tuple[Ticket, ...]:
        """Close resolved tickets with no activity for `after` (§9's resolved 14 days).

        Only `RESOLVED` tickets are eligible, and that is the whole point of resolved and closed
        being separate states: the window exists so a user can say "that did not fix it" before
        the thread shuts. Auto-closing from `OPEN` would shut tickets nobody ever answered,
        which is the opposite of a convenience.

        Runs as a Background Workers interval job rather than on a read path — a sweep that only
        happened when someone opened the queue would leave a quiet install's tickets open
        forever.
        """
        cutoff = self._now() - after
        closed: list[Ticket] = []
        with self._lock:
            for ticket_id, ticket in list(self._tickets.items()):
                if ticket.status is not TicketStatus.RESOLVED or ticket.updated_at > cutoff:
                    continue
                updated = self._replace(ticket, status=TicketStatus.CLOSED)
                self._tickets[ticket_id] = updated
                closed.append(updated)
        if closed:
            self._metrics.increment("tickets_auto_closed", len(closed))
        return tuple(closed)

    # ---------------------------------------------------------------------- internals

    def _touch(self, ticket: Ticket) -> Ticket:
        return self._replace(ticket)

    def _replace(self, ticket: Ticket, **changes) -> Ticket:
        """A frozen-contract update with `updated_at` always refreshed.

        Centralised so no path can change a ticket without moving its activity timestamp —
        which §9's auto-close reads, so a missed touch would close a thread someone just replied
        to.
        """
        return Ticket(
            ticket_id=ticket.ticket_id,
            created_by=ticket.created_by,
            subject=changes.get("subject", ticket.subject),
            status=changes.get("status", ticket.status),
            assigned_to=changes.get("assigned_to", ticket.assigned_to),
            related_receipt_id=changes.get("related_receipt_id", ticket.related_receipt_id),
            created_at=ticket.created_at,
            updated_at=self._now(),
        )


__all__ = [
    "SessionResolver",
    "TicketStore",
    "can_transition",
    "deny_all_sessions",
    "new_ticket_id",
]

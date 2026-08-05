"""The ticket lifecycle, routing, and both testing hooks §8 names (§2, §4, §8, §9).

* **Break-glass reference resolution test** — "confirms a break-glass grant's own `reason`
  field, when it happens to reference a real ticket ID, actually resolves to a real `Ticket`
  record — a real, if soft, integration point worth a regression test given how easily the two
  could silently drift apart otherwise."
* **Receipt-context jump test** — "confirms a ticket with `related_receipt_id` set correctly
  deep-links staff to that receipt's own detail screen."

The break-glass one is the subtle hook, and §8 says why: the link is *soft*. §1 forbids making
a ticket mandatory for a grant, so nothing fails when resolution stops working — every grant
keeps being issued exactly as before and the reference quietly resolves to nothing. There is no
error to notice. A regression test is the only thing standing between that and silent drift.

§4's routing simplicity is deliberate and tested as such: the one rule with teeth is that
self-assign does not mean "take anyone's work".
"""

from __future__ import annotations

import pytest

from core.support_ticketing.assignment import REASSIGN_ROLES, STAFF_ROLES
from core.support_ticketing.contracts import (
    AUTO_CLOSE_AFTER,
    VALID_TRANSITIONS,
    AuthorKind,
    TicketListQuery,
    TicketStatus,
)
from core.support_ticketing.errors import RoleForbidden, TicketAccessDenied
from core.support_ticketing.lifecycle import TicketStore, can_transition, deny_all_sessions

from .conftest import CLIENT_SESSION, OWNER_SESSION, STAFF_SESSION, STAFF2_SESSION


def open_ticket(store: TicketStore, *, receipt: str | None = None, session=CLIENT_SESSION):
    return store.create_ticket(
        session, "Why was this receipt flagged?", body="It looks fine to me.", related_receipt_id=receipt
    ).ticket


# ------------------------------------------------------------------------- the basics


def test_a_user_opens_a_ticket_and_it_starts_open_and_unassigned(store):
    ticket = open_ticket(store)

    assert ticket.status is TicketStatus.OPEN
    assert ticket.assigned_to is None
    assert ticket.created_by == "client-1"


def test_the_opening_body_becomes_the_first_message(store):
    ticket = open_ticket(store)

    messages = store.messages_for(CLIENT_SESSION, ticket.ticket_id)

    assert len(messages) == 1
    assert messages[0].author_kind is AuthorKind.USER
    assert messages[0].author == "user"


def test_a_staff_reply_is_attributed_as_staff(store):
    """§3's own wire shape is `"staff:<user_id>"`, derived rather than stored.

    A stored string could disagree with the fields it renders — and in a support thread, an
    attribution that says "user" for a staff reply misleads the person reading it about who
    they are talking to.
    """
    ticket = open_ticket(store)

    store.post_message(STAFF_SESSION, ticket.ticket_id, "Looking into it now.")
    messages = store.messages_for(STAFF_SESSION, ticket.ticket_id)

    assert messages[-1].author == "staff:staff-1"


def test_a_ticket_with_no_subject_is_rejected(store):
    """Not defaulted to "(no subject)".

    A staff queue where several rows share a placeholder title is a queue nobody can triage.
    """
    result = store.create_ticket(CLIENT_SESSION, "   ")

    assert not result.ok
    assert result.error_code == "INVALID_TICKET_REQUEST"


def test_an_unresolvable_session_cannot_open_a_ticket():
    """The default resolver denies, which is what a process with Auth unwired gets."""
    store = TicketStore(sessions=deny_all_sessions)

    result = store.create_ticket("whatever", "subject")

    assert not result.ok
    assert result.error_code == "ROLE_FORBIDDEN"


# ------------------------------------------------------------------------- isolation


def test_a_user_cannot_read_another_users_ticket(store):
    """Support conversations quote receipt details, amounts and vendor names.

    A ticket is per-user data in the same sense a receipt is, which is why this is a real
    check rather than a listing convenience.
    """
    ticket = open_ticket(store)

    with pytest.raises(TicketAccessDenied):
        store.messages_for("sess-other-client", ticket.ticket_id)


def test_a_denied_read_raises_rather_than_returning_an_empty_conversation(store):
    """An empty thread and a forbidden one are different facts.

    Returning `()` for both would let a caller render "no messages yet" for someone else's
    ticket — which looks like a working feature and is a disclosure of the ticket's existence.
    """
    ticket = open_ticket(store)

    with pytest.raises(TicketAccessDenied):
        store.messages_for("sess-other-client", ticket.ticket_id)


def test_staff_can_read_any_ticket(store):
    ticket = open_ticket(store)

    assert store.messages_for(STAFF_SESSION, ticket.ticket_id)


def test_a_clients_listing_is_narrowed_to_their_own_rather_than_refused(store):
    """A user asking for "all tickets" obviously means their own.

    Refusing it would be a confusing error for a request that has an obvious correct answer.
    """
    open_ticket(store)
    store.create_ticket("sess-other-client", "Another user's problem")

    listed = store.list_tickets(CLIENT_SESSION, TicketListQuery())

    assert {t.created_by for t in listed.tickets} == {"client-1"}


# --------------------------------------------------------------- §4's routing rules


def test_any_staff_member_can_self_assign_an_unassigned_ticket(store):
    """§4: "an unassigned ticket is visible to any staff member, any staff member can
    self-assign"."""
    ticket = open_ticket(store)

    result = store.assign_ticket(STAFF_SESSION, ticket.ticket_id, "staff-1")

    assert result.ok
    assert result.ticket.assigned_to == "staff-1"


def test_self_assigning_moves_an_open_ticket_into_progress(store):
    """Picking a ticket up *is* starting work on it; leaving it OPEN would make the queue lie
    about what is unattended."""
    ticket = open_ticket(store)

    result = store.assign_ticket(STAFF_SESSION, ticket.ticket_id, "staff-1")

    assert result.ticket.status is TicketStatus.IN_PROGRESS


def test_one_staff_member_cannot_take_a_ticket_from_another(store):
    """The one routing rule with real teeth.

    Without it, "any staff member can self-assign" silently means "any staff member can
    un-assign anyone", and a thread could be pulled away mid-conversation — a queue where
    nobody can rely on owning a thread.
    """
    ticket = open_ticket(store)
    store.assign_ticket(STAFF_SESSION, ticket.ticket_id, "staff-1")

    result = store.assign_ticket(STAFF2_SESSION, ticket.ticket_id, "staff-2")

    assert not result.ok
    assert result.error_code == "ROLE_FORBIDDEN"


def test_an_owner_can_reassign(store):
    """§4: "an owner can reassign"."""
    ticket = open_ticket(store)
    store.assign_ticket(STAFF_SESSION, ticket.ticket_id, "staff-1")

    result = store.assign_ticket(OWNER_SESSION, ticket.ticket_id, "staff-2")

    assert result.ok
    assert result.ticket.assigned_to == "staff-2"
    assert store.metrics.snapshot().tickets_reassigned == 1


def test_a_client_cannot_assign_a_ticket_at_all(store):
    ticket = open_ticket(store)

    result = store.assign_ticket(CLIENT_SESSION, ticket.ticket_id, "staff-1")

    assert not result.ok


def test_staff_can_reclaim_a_ticket_they_already_hold(store):
    """Re-assigning to yourself is a no-op, not a forbidden reassignment."""
    ticket = open_ticket(store)
    store.assign_ticket(STAFF_SESSION, ticket.ticket_id, "staff-1")

    assert store.assign_ticket(STAFF_SESSION, ticket.ticket_id, "staff-1").ok


def test_the_unassigned_queue_is_what_staff_pick_from(store):
    """§4's shared queue makes "what can I pick up" the most common staff question."""
    first = open_ticket(store)
    second = open_ticket(store)
    store.assign_ticket(STAFF_SESSION, first.ticket_id, "staff-1")

    available = store.list_tickets(STAFF_SESSION, TicketListQuery(unassigned_only=True))

    assert [t.ticket_id for t in available.tickets] == [second.ticket_id]


def test_the_routing_model_stays_as_simple_as_section_4_decided():
    """§4 and §9 both argue against priority/SLA machinery at this project's scale.

    Asserted as data so adding a priority tier has to be a deliberate decision that breaks a
    test naming the reasoning, rather than something that accretes.
    """
    assert STAFF_ROLES == frozenset({"staff", "owner"})
    assert REASSIGN_ROLES == frozenset({"owner"})


# ------------------------------------------------------------------ the state machine


@pytest.mark.parametrize(
    "target", [TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED]
)
def test_a_closed_ticket_is_terminal(target):
    assert not can_transition(TicketStatus.CLOSED, target)


def test_a_resolved_ticket_can_be_reopened(store):
    """A user replying "that didn't fix it" is the ordinary case.

    Forcing a second ticket would lose the conversation that explains the problem — which is
    the thing staff need most when the first attempt did not work.
    """
    ticket = open_ticket(store)
    store.set_status(STAFF_SESSION, ticket.ticket_id, TicketStatus.RESOLVED)

    result = store.set_status(STAFF_SESSION, ticket.ticket_id, TicketStatus.IN_PROGRESS)

    assert result.ok
    assert store.metrics.snapshot().tickets_reopened == 1


def test_reopening_a_closed_ticket_is_refused_explicitly(store):
    """Refused rather than silently ignored.

    A silent no-op returns success to someone whose action did nothing — in support, that means
    a user believing staff were told something they never were.
    """
    ticket = open_ticket(store)
    store.set_status(STAFF_SESSION, ticket.ticket_id, TicketStatus.CLOSED)

    result = store.set_status(STAFF_SESSION, ticket.ticket_id, TicketStatus.IN_PROGRESS)

    assert not result.ok
    assert result.error_code == "INVALID_STATUS_TRANSITION"


def test_a_user_can_close_their_own_ticket(store):
    """Someone who worked out their own answer needs a way to withdraw it.

    Refusing would fill the staff queue with resolved-in-practice threads nobody can clear.
    """
    ticket = open_ticket(store)

    assert store.set_status(CLIENT_SESSION, ticket.ticket_id, TicketStatus.CLOSED).ok


def test_a_user_cannot_change_another_users_ticket(store):
    ticket = open_ticket(store)

    result = store.set_status("sess-other-client", ticket.ticket_id, TicketStatus.CLOSED)

    assert not result.ok


def test_the_transition_table_is_the_single_source_of_truth():
    """`can_transition` reads `VALID_TRANSITIONS` rather than restating it."""
    for current, targets in VALID_TRANSITIONS.items():
        for target in TicketStatus:
            assert can_transition(current, target) == (target in targets)


# ------------------------------------------------------- §8's break-glass reference hook


def test_a_break_glass_reason_naming_a_real_ticket_resolves_to_it(store):
    """§8's first hook, verbatim.

    Auth's break-glass reason is free text. This proves a reason that happens to name a ticket
    genuinely reaches the `Ticket` record — the "real, if soft, integration point" §8 wants a
    regression test for.
    """
    ticket = open_ticket(store)

    resolved = store.resolve_break_glass_reference(
        f"Investigating {ticket.ticket_id} at the user's request"
    )

    assert resolved is not None
    assert resolved.ticket_id == ticket.ticket_id


def test_a_reason_naming_no_ticket_resolves_to_nothing_and_that_is_fine(store):
    """§1: this API "doesn't require every break-glass grant to have a formal ticket behind it".

    So a reason with no reference is not an error — it is the normal case for most grants, and
    treating it as a failure would make the link a requirement §1 explicitly rejects.
    """
    assert store.resolve_break_glass_reference("User asked me to look at their August receipts") is None


def test_a_reason_naming_a_ticket_that_does_not_exist_resolves_to_nothing(store):
    """A typo'd or stale reference must not resurrect a ticket or raise."""
    assert store.resolve_break_glass_reference("see TKT-DEADBEEF1234 for context") is None


def test_the_resolution_ratio_is_what_would_reveal_silent_drift(store):
    """Why this hook exists at all.

    §8 names the risk as the two "silently drifting apart" — if ticket ids stopped being
    findable in prose, every grant would keep working exactly as before and nothing would
    fail. These counters are the only signal that would move.
    """
    ticket = open_ticket(store)
    store.resolve_break_glass_reference(f"ref {ticket.ticket_id}")
    store.resolve_break_glass_reference("no reference at all")

    snapshot = store.metrics.snapshot()
    assert snapshot.break_glass_refs_resolved == 1
    assert snapshot.break_glass_refs_unresolvable == 1


def test_a_ticket_id_is_findable_inside_ordinary_prose(store):
    """The property the whole hook rests on.

    A bare UUID inside a sentence is not extractable; the `TKT-` prefix is what makes the soft
    link work at all, which is why it is part of the id rather than presentation.
    """
    ticket = open_ticket(store)

    for phrasing in (
        f"{ticket.ticket_id}",
        f"per {ticket.ticket_id}.",
        f"(see {ticket.ticket_id})",
        f"context: {ticket.ticket_id}, user asked",
    ):
        assert store.resolve_break_glass_reference(phrasing) is not None


# --------------------------------------------------------- §8's receipt-context hook


def test_a_ticket_naming_a_receipt_deep_links_staff_to_it(store):
    """§8's second hook.

    §3 calls `related_receipt_id` "a deliberate, real field, not an afterthought" because so
    many support questions in this domain are about one receipt — and the payoff is staff
    jumping straight to it rather than asking the user to describe what they are looking at.
    """
    ticket = open_ticket(store, receipt="rcpt-42")

    assert store.receipt_context_for(STAFF_SESSION, ticket.ticket_id) == "rcpt-42"
    assert ticket.links_a_receipt


def test_a_ticket_with_no_receipt_returns_nothing_rather_than_a_placeholder(store):
    ticket = open_ticket(store)

    assert store.receipt_context_for(STAFF_SESSION, ticket.ticket_id) is None
    assert not ticket.links_a_receipt


def test_the_receipt_context_is_gated_like_the_ticket_itself(store):
    """Otherwise the deep link leaks which receipt another user's ticket concerns."""
    ticket = open_ticket(store, receipt="rcpt-42")

    with pytest.raises(TicketAccessDenied):
        store.receipt_context_for("sess-other-client", ticket.ticket_id)


def test_tickets_can_be_found_by_the_receipt_they_concern(store):
    """The other direction of the same link: staff on a receipt asking "has anyone raised this"."""
    linked = open_ticket(store, receipt="rcpt-42")
    open_ticket(store)

    found = store.list_tickets(STAFF_SESSION, TicketListQuery(related_receipt_id="rcpt-42"))

    assert [t.ticket_id for t in found.tickets] == [linked.ticket_id]


# ----------------------------------------------------------------- §9's auto-close


def test_a_resolved_ticket_auto_closes_after_the_window(store, clock):
    """§9's resolved 14 days."""
    ticket = open_ticket(store)
    store.set_status(STAFF_SESSION, ticket.ticket_id, TicketStatus.RESOLVED)

    clock.advance_days(15)
    closed = store.auto_close_stale()

    assert [t.ticket_id for t in closed] == [ticket.ticket_id]
    assert closed[0].status is TicketStatus.CLOSED


def test_a_resolved_ticket_inside_the_window_stays_open(store, clock):
    ticket = open_ticket(store)
    store.set_status(STAFF_SESSION, ticket.ticket_id, TicketStatus.RESOLVED)

    clock.advance_days(13)

    assert store.auto_close_stale() == ()


def test_an_open_ticket_never_auto_closes_however_old(store, clock):
    """The reason resolved and closed are separate states.

    Auto-closing from OPEN would shut tickets nobody ever answered — the opposite of a
    convenience, and exactly the behaviour that makes users stop filing them.
    """
    open_ticket(store)

    clock.advance_days(365)

    assert store.auto_close_stale() == ()


def test_a_reply_to_a_resolved_ticket_restarts_the_window(store, clock):
    """Activity is what the window measures.

    A user replying on day 13 must not have their thread closed on day 15 — that is precisely
    the case the two-week window exists to protect.
    """
    ticket = open_ticket(store)
    store.set_status(STAFF_SESSION, ticket.ticket_id, TicketStatus.RESOLVED)

    clock.advance_days(13)
    store.post_message(CLIENT_SESSION, ticket.ticket_id, "Actually that did not fix it")
    clock.advance_days(3)

    assert store.auto_close_stale() == ()


def test_the_window_is_the_fourteen_days_section_9_resolved():
    assert AUTO_CLOSE_AFTER.days == 14

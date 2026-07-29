"""Staff assignment and routing (§4, §9).

§4 is unusually explicit that the simplicity here is a decision rather than an omission:

> Simple, deliberately not over-engineered for this project's actual scale: an unassigned
> ticket is visible to any staff member, any staff member can self-assign, an owner can
> reassign. No complex routing rules, priority queues, or SLA tracking in this version —
> genuinely not warranted at the scale this project's own staff team operates at, and adding
> that complexity speculatively would be exactly the kind of premature scope this project's own
> "reasoned, then measured" discipline argues against.

§9 reinforces it by resolving tier-based priority as "no, not in v1" for the same reason. So
this module is small on purpose, and a future session reading it should treat its size as the
design rather than as something unfinished.

The one rule with real teeth is **reassignment**. A staff member may take an unassigned ticket
or one they already hold; taking a ticket out of a colleague's hands is an owner action. Without
that line, "any staff member can self-assign" would silently mean "any staff member can
un-assign anyone", and a queue where work can be pulled away mid-conversation is one where
nobody can rely on owning a thread.

Review/Flagging resolves the structurally identical question the same way (its §8 cites this
document by name), which is why the two read alike — deliberately one routing philosophy across
both staff queues rather than two.
"""

from __future__ import annotations

from .contracts import Ticket
from .errors import RoleForbidden

#: Roles permitted to act on a ticket as staff at all. Anything else is a `client`, who may
#: only ever act on their own tickets and never assign one.
STAFF_ROLES: frozenset[str] = frozenset({"staff", "owner"})

#: The role permitted to take a ticket away from whoever currently holds it (§4).
REASSIGN_ROLES: frozenset[str] = frozenset({"owner"})


def is_staff(role: str) -> bool:
    return role in STAFF_ROLES


def may_view(ticket: Ticket, actor_user_id: str, role: str) -> bool:
    """Staff see every ticket; a user sees only their own.

    Support conversations routinely quote receipt details, amounts and vendor names, so a
    ticket is per-user data in the same sense a receipt is — which is why this is a real check
    rather than a listing convenience.
    """
    if is_staff(role):
        return True
    return ticket.created_by == actor_user_id


def may_post(ticket: Ticket, actor_user_id: str, role: str) -> bool:
    """Who may add to the conversation.

    Same rule as viewing: if you can read the thread you can reply to it. A user replying to
    their own ticket is the entire point of a conversation rather than a form submission.
    """
    return may_view(ticket, actor_user_id, role)


def authorize_assignment(
    ticket: Ticket, actor_user_id: str, role: str, assignee_user_id: str
) -> None:
    """Raise `RoleForbidden` unless this actor may set this ticket's assignee (§4).

    Three cases, and the third is the one that matters:

    1. Not staff at all — denied. A user cannot assign their own ticket to someone.
    2. Staff, and the ticket is unassigned or already theirs — allowed. This is §4's
       "any staff member can self-assign".
    3. Staff, and the ticket is held by *someone else* — denied unless owner. Otherwise
       "self-assign" quietly means "take anyone's work", and a thread could be pulled away
       mid-conversation.
    """
    if not is_staff(role):
        raise RoleForbidden("only staff may assign a ticket")
    if ticket.assigned_to in (None, actor_user_id):
        return
    if role not in REASSIGN_ROLES:
        raise RoleForbidden(
            f"ticket is assigned to {ticket.assigned_to!r}; only an owner may reassign it"
        )


def authorize_status_change(ticket: Ticket, actor_user_id: str, role: str) -> None:
    """Raise `RoleForbidden` unless this actor may move this ticket's status.

    Staff may move any ticket. A user may act on their own ticket, which covers the real case
    of a user closing a question they worked out themselves — refusing that would leave them
    with no way to withdraw a ticket and would fill the staff queue with resolved-in-practice
    threads nobody can clear.
    """
    if is_staff(role):
        return
    if ticket.created_by != actor_user_id:
        raise RoleForbidden("only staff or the ticket's own author may change its status")


__all__ = [
    "REASSIGN_ROLES",
    "STAFF_ROLES",
    "authorize_assignment",
    "authorize_status_change",
    "is_staff",
    "may_post",
    "may_view",
]

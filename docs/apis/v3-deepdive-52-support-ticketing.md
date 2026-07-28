# V3 Deep Dive: Support Ticketing API

**Companion files:** `v3-deepdive-05-auth-tenancy-api.md` §6 (break-glass's own `reason` field already assumed a "support ticket ref" existed as something to point at — this API is what that reference was always implicitly counting on), `v3-deepdive-09-notifications-inbox-api.md` (ticket updates route through the existing inbox, not a second notification mechanism).

**Status:** New Core API (#31), surfaced as a genuine blind spot during a corpus-wide sweep — a "support ticket" was referenced as if it already existed, but nothing anywhere actually built one.

---

## 1. Scope & boundary

Support Ticketing owns a real ticket lifecycle — a user or staff member opens a ticket, staff responds, it resolves — genuinely in-app, not a wrapper around an external tool. It does not:
- **own notification delivery** — a new ticket message triggers a Notifications API entry (its deep-dive) the same way any other in-app event does; this API owns ticket state and conversation content, not how a user gets told about it.
- **replace break-glass's own reason field** — break-glass (`v3-deepdive-05-auth-tenancy-api.md` §6) still just takes a free-text reason; this API gives that reason field somewhere real to *point at* when the underlying context is a genuine support interaction, but doesn't require every break-glass grant to have a formal ticket behind it.
- **handle account-recovery case intake** — Account Guardian's own `account_recovery.py` (its deep-dive §5) already owns that specific, higher-stakes staff-mediated queue; a garden-variety support question ("why was my receipt flagged") is this API's job, an identity-verification case is Account Guardian's.

---

## 2. Package layout

```
core/support_ticketing/
  __init__.py
  contracts.py             # Ticket, TicketMessage, error types
  lifecycle.py                # open → in_progress → resolved → closed
  assignment.py                  # staff assignment/routing
  errors.py
```

---

## 3. Data contracts

```python
@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    created_by: str              # user_id
    subject: str
    status: Literal["open", "in_progress", "resolved", "closed"]
    assigned_to: str | None        # staff user_id
    related_receipt_id: str | None   # optional — many tickets are "why was this receipt flagged"-shaped
    created_at: datetime

@dataclass(frozen=True)
class TicketMessage:
    ticket_id: str
    author: str                    # "user" | "staff:<user_id>"
    body: str
    posted_at: datetime
```
`related_receipt_id` is a deliberate, real field, not an afterthought — given how many support questions in this specific domain are genuinely about one receipt ("why did this get flagged," "this vendor match looks wrong") — a ticket that references a receipt lets staff jump straight to that receipt's own detail screen (`v3-deepdive-48-receipt-detail-screen.md`) and its full Historian narrative, rather than staff having to ask the user to describe what they're looking at.

---

## 4. Staff assignment and routing
Simple, deliberately not over-engineered for this project's actual scale: an unassigned ticket is visible to any staff member, any staff member can self-assign, an owner can reassign. No complex routing rules, priority queues, or SLA tracking in this version — genuinely not warranted at the scale this project's own staff team operates at, and adding that complexity speculatively would be exactly the kind of premature scope this project's own "reasoned, then measured" discipline argues against.

---

## 5. Where this surfaces in the TUI/webapp
A staff-facing ticket queue — genuinely another instance of the `DataTable` pattern (`v3-deepdive-45-design-system.md` §3) for the webapp side, and a natural addition to the TUI's own staff audit-review queue (already an enumerated custom-screen exception, `v3-deepdive-14-interface-api.md` §3.2) rather than a wholly new TUI screen, given the same underlying interaction shape (a queue of things staff need to look at and act on) that screen already handles for contribution/flag review.

---

## 6. Asyncio, free-threading, and profiling
Thin CRUD over its own small database — the same I/O-bound, no-compute-of-its-own shape as every other thin-orchestration API in this batch (Tool Call, Account Guardian, Groups). **Forward-compatibility check, explicit rather than assumed**: no new dependency of any kind introduced by this API — pure CRUD over an already-established SQLite/async-wrapper stack, nothing requiring a new Telemetrees entry.

---

## 7. gRPC surface

```protobuf
service SupportTicketingService {
  rpc CreateTicket(CreateTicketRequest) returns (TicketResponse);
  rpc PostMessage(PostMessageRequest) returns (TicketMessageResponse);
  rpc UpdateTicketStatus(UpdateStatusRequest) returns (TicketResponse);
  rpc AssignTicket(AssignRequest) returns (TicketResponse);
  rpc ListTickets(ListTicketsRequest) returns (ListTicketsResponse);
}
```

---

## 8. Testing hooks
- **Break-glass reference resolution test**: confirms a break-glass grant's own `reason` field, when it happens to reference a real ticket ID, actually resolves to a real `Ticket` record — a real, if soft, integration point worth a regression test given how easily the two could silently drift apart otherwise.
- **Receipt-context jump test**: confirms a ticket with `related_receipt_id` set correctly deep-links staff to that receipt's own detail screen.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Tier-based support priority, resolved: no, not in v1.** Consistent with this document's own §4 reasoning against premature routing/priority complexity at this project's actual scale — the same "reasoned, then measured" discipline, not a new exception to it.
- **Ticket-to-break-glass linkage, resolved: yes, offer the shortcut, don't require it.** Break-glass's own reason field gains a real "create/link a ticket" affordance — a genuine, low-cost UX improvement that strengthens the connection between the two without making a formal ticket mandatory for every grant, consistent with §1's own stated boundary.
- **Auto-closing stale resolved tickets, resolved: yes, 14 days.** A standard, reasonable ticketing-system convenience — a resolved ticket with no further activity for two weeks auto-closes rather than sitting open indefinitely.

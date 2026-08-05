"""`SupportTicketingServicer` — the real assembly point wiring `lifecycle.TicketStore`
to `support_ticketing.proto`'s wire surface. This was a real, complete gap: the
package's own `CLAUDE.md` named it by name ("§7 specifies a five-RPC surface and there
is no `.proto` here yet")."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.support_ticketing.generated import support_ticketing_pb2 as pb  # noqa: E402
from core.support_ticketing.service import SupportTicketingServicer  # noqa: E402

from .conftest import CLIENT_SESSION, OWNER_SESSION, STAFF2_SESSION, STAFF_SESSION  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_create_ticket_rpc_opens_a_ticket_with_an_initial_message(store):
    servicer = SupportTicketingServicer(store)

    response = run(servicer.CreateTicket(pb.CreateTicketRequest(
        session_id=CLIENT_SESSION, subject="Why was my receipt flagged?",
        body="Vendor match looks wrong", related_receipt_id="receipt-1",
    )))

    assert response.error_code == ""
    assert response.ticket.status == "open"
    assert response.ticket.ticket_id.startswith("TKT-")
    assert response.ticket.related_receipt_id == "receipt-1"

    messages = run(servicer.GetTicketMessages(pb.GetTicketMessagesRequest(
        session_id=CLIENT_SESSION, ticket_id=response.ticket.ticket_id,
    )))
    assert len(messages.messages) == 1
    assert messages.messages[0].author == "user"


def test_create_ticket_rpc_rejects_an_empty_subject(store):
    servicer = SupportTicketingServicer(store)

    response = run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="  ")))

    assert response.error_code != ""
    assert not response.HasField("ticket")


def test_get_ticket_messages_denies_a_different_client(store):
    servicer = SupportTicketingServicer(store)
    created = run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="s")))

    response = run(servicer.GetTicketMessages(pb.GetTicketMessagesRequest(
        session_id="sess-other-client", ticket_id=created.ticket.ticket_id,
    )))

    assert response.error_code == "TICKET_ACCESS_DENIED"


def test_assign_ticket_rpc_self_assigns_and_moves_to_in_progress(store):
    servicer = SupportTicketingServicer(store)
    created = run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="s")))

    response = run(servicer.AssignTicket(pb.AssignRequest(
        session_id=STAFF_SESSION, ticket_id=created.ticket.ticket_id, assignee_user_id="staff-1",
    )))

    assert response.error_code == ""
    assert response.ticket.assigned_to == "staff-1"
    assert response.ticket.status == "in_progress"


def test_assign_ticket_rpc_denies_a_different_staff_member_taking_it_over(store):
    servicer = SupportTicketingServicer(store)
    created = run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="s")))
    run(servicer.AssignTicket(pb.AssignRequest(
        session_id=STAFF_SESSION, ticket_id=created.ticket.ticket_id, assignee_user_id="staff-1",
    )))

    response = run(servicer.AssignTicket(pb.AssignRequest(
        session_id=STAFF2_SESSION, ticket_id=created.ticket.ticket_id, assignee_user_id="staff-2",
    )))

    assert response.error_code == "ROLE_FORBIDDEN"


def test_assign_ticket_rpc_lets_an_owner_reassign(store):
    servicer = SupportTicketingServicer(store)
    created = run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="s")))
    run(servicer.AssignTicket(pb.AssignRequest(
        session_id=STAFF_SESSION, ticket_id=created.ticket.ticket_id, assignee_user_id="staff-1",
    )))

    response = run(servicer.AssignTicket(pb.AssignRequest(
        session_id=OWNER_SESSION, ticket_id=created.ticket.ticket_id, assignee_user_id="staff-2",
    )))

    assert response.error_code == ""
    assert response.ticket.assigned_to == "staff-2"


def test_post_message_rpc_records_a_staff_reply(store):
    servicer = SupportTicketingServicer(store)
    created = run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="s")))

    response = run(servicer.PostMessage(pb.PostMessageRequest(
        session_id=STAFF_SESSION, ticket_id=created.ticket.ticket_id, body="Looking into it",
    )))

    assert response.error_code == ""
    assert response.message.author == "staff:staff-1"


def test_update_ticket_status_rpc_moves_to_resolved(store):
    servicer = SupportTicketingServicer(store)
    created = run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="s")))

    response = run(servicer.UpdateTicketStatus(pb.UpdateStatusRequest(
        session_id=STAFF_SESSION, ticket_id=created.ticket.ticket_id, target_status="resolved",
    )))

    assert response.error_code == ""
    assert response.ticket.status == "resolved"


def test_update_ticket_status_rpc_rejects_reopening_a_closed_ticket(store):
    servicer = SupportTicketingServicer(store)
    created = run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="s")))
    run(servicer.UpdateTicketStatus(pb.UpdateStatusRequest(
        session_id=STAFF_SESSION, ticket_id=created.ticket.ticket_id, target_status="resolved",
    )))
    run(servicer.UpdateTicketStatus(pb.UpdateStatusRequest(
        session_id=STAFF_SESSION, ticket_id=created.ticket.ticket_id, target_status="closed",
    )))

    response = run(servicer.UpdateTicketStatus(pb.UpdateStatusRequest(
        session_id=STAFF_SESSION, ticket_id=created.ticket.ticket_id, target_status="in_progress",
    )))

    assert response.error_code == "INVALID_STATUS_TRANSITION"


def test_update_ticket_status_rpc_reports_invalid_status_for_a_bad_string(store):
    servicer = SupportTicketingServicer(store)
    created = run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="s")))

    response = run(servicer.UpdateTicketStatus(pb.UpdateStatusRequest(
        session_id=STAFF_SESSION, ticket_id=created.ticket.ticket_id, target_status="not_a_real_status",
    )))

    assert response.error_code == "INVALID_STATUS"


def test_list_tickets_rpc_narrows_a_client_to_their_own_tickets(store):
    servicer = SupportTicketingServicer(store)
    run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="mine")))
    run(servicer.CreateTicket(pb.CreateTicketRequest(session_id="sess-other-client", subject="not mine")))

    response = run(servicer.ListTickets(pb.ListTicketsRequest(session_id=CLIENT_SESSION)))

    assert len(response.tickets) == 1
    assert response.tickets[0].subject == "mine"


def test_list_tickets_rpc_shows_staff_every_ticket(store):
    servicer = SupportTicketingServicer(store)
    run(servicer.CreateTicket(pb.CreateTicketRequest(session_id=CLIENT_SESSION, subject="a")))
    run(servicer.CreateTicket(pb.CreateTicketRequest(session_id="sess-other-client", subject="b")))

    response = run(servicer.ListTickets(pb.ListTicketsRequest(session_id=STAFF_SESSION)))

    assert len(response.tickets) == 2

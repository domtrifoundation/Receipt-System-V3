"""The `SupportTicketingServicer` gRPC servicer (`support_ticketing.proto`) — the real
assembly point wiring `lifecycle.TicketStore` to the wire surface.

**This was a real, complete gap, not a documented placeholder** — the package's own
`CLAUDE.md` named it explicitly: "§7 specifies a five-RPC surface and there is no
`.proto` here yet." `contracts.py`, `assignment.py`, `lifecycle.py`, `errors.py`, and
`metrics.py` were all real and independently tested; nothing outside an in-process
Python caller could reach any of it.

**`TicketStore`'s own methods are synchronous** (`lifecycle.py`'s own in-memory-plus-lock
design, not `async def`) — this servicer's RPC methods are still declared `async def` to
match every other API's servicer convention in this project, but each one calls straight
into the synchronous store; there is no blocking I/O inside `TicketStore` to worry about
(everything is an in-memory dict behind a real `threading.Lock`).

**`GrpcSessionResolver` is a real, synchronous client against Auth's `ValidateSession`**
— synchronous because `lifecycle.SessionResolver`'s own type is `Callable[[str],
tuple[str, str] | None]`, not an async callable; this uses a plain `grpc.insecure_channel`
rather than `grpc.aio`, the one place in this session's work where a client had to be
built against a sync signature instead of async.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from .contracts import TicketListQuery, TicketStatus
from .lifecycle import TicketStore, deny_all_sessions

DEFAULT_ADDRESS = "127.0.0.1:50082"
DEFAULT_AUTH_ADDRESS = "127.0.0.1:50056"

__all__ = ["DEFAULT_ADDRESS", "GrpcSessionResolver", "SupportTicketingServicer", "serve"]


class GrpcSessionResolver:
    """Resolves `(user_id, role)` from Auth & Tenancy's real `ValidateSession` RPC,
    synchronously — `lifecycle.SessionResolver`'s own type is a plain callable, not a
    coroutine function. Any failure (invalid/expired session, Auth unreachable) resolves
    to `None`, never partial trust (`docs/PRINCIPLES.md` §4.2)."""

    def __init__(self, address: str = DEFAULT_AUTH_ADDRESS) -> None:
        self._address = address

    def __call__(self, session_id: str) -> tuple[str, str] | None:
        if not session_id:
            return None
        import grpc

        from core.auth.generated import auth_pb2 as pb
        from core.auth.generated import auth_pb2_grpc as pb_grpc

        try:
            with grpc.insecure_channel(self._address) as channel:
                stub = pb_grpc.AuthServiceStub(channel)
                resp = stub.ValidateSession(pb.ValidateSessionRequest(session_id=session_id), timeout=5.0)
        except grpc.RpcError:
            return None
        if resp.error_code or not resp.user_id or not resp.role:
            return None
        return (resp.user_id, resp.role)


def _ticket_to_pb(pb, ticket):
    return pb.TicketInfo(
        ticket_id=ticket.ticket_id, created_by=ticket.created_by, subject=ticket.subject,
        status=ticket.status.value, assigned_to=ticket.assigned_to or "",
        related_receipt_id=ticket.related_receipt_id or "",
        created_at=ticket.created_at.isoformat(), updated_at=ticket.updated_at.isoformat(),
    )


def _ticket_response(pb, result):
    response = pb.TicketResponse(error_code=result.error_code, error_detail=result.error_detail)
    if result.ticket is not None:
        response.ticket.CopyFrom(_ticket_to_pb(pb, result.ticket))
    return response


def _message_to_pb(pb, message):
    return pb.TicketMessageInfo(
        ticket_id=message.ticket_id, author=message.author, body=message.body,
        posted_at=message.posted_at.isoformat(),
    )


class SupportTicketingServicer:
    """Implements `SupportTicketingService`. Registered by name, so importing the
    generated stubs is `serve()`'s business and this class stays importable without
    them."""

    def __init__(self, store: TicketStore | None = None) -> None:
        self._store = store if store is not None else TicketStore(sessions=deny_all_sessions)

    async def CreateTicket(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import support_ticketing_pb2 as pb

        result = self._store.create_ticket(
            request.session_id, request.subject, body=request.body,
            related_receipt_id=request.related_receipt_id or None,
        )
        return _ticket_response(pb, result)

    async def PostMessage(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import support_ticketing_pb2 as pb

        result = self._store.post_message(request.session_id, request.ticket_id, request.body)
        response = pb.TicketMessageResponse(error_code=result.error_code, error_detail=result.error_detail)
        if result.message is not None:
            response.message.CopyFrom(_message_to_pb(pb, result.message))
        return response

    async def GetTicketMessages(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import support_ticketing_pb2 as pb
        from .errors import SupportTicketingError, code_for

        response = pb.ListMessagesResponse()
        try:
            messages = self._store.messages_for(request.session_id, request.ticket_id)
        except SupportTicketingError as exc:
            response.error_code = code_for(exc)
            response.error_detail = str(exc)
            return response
        for message in messages:
            response.messages.append(_message_to_pb(pb, message))
        return response

    async def UpdateTicketStatus(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import support_ticketing_pb2 as pb

        try:
            target = TicketStatus(request.target_status)
        except ValueError:
            return pb.TicketResponse(error_code="INVALID_STATUS", error_detail=f"unknown status {request.target_status!r}")
        result = self._store.set_status(request.session_id, request.ticket_id, target)
        return _ticket_response(pb, result)

    async def AssignTicket(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import support_ticketing_pb2 as pb

        result = self._store.assign_ticket(request.session_id, request.ticket_id, request.assignee_user_id)
        return _ticket_response(pb, result)

    async def ListTickets(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import support_ticketing_pb2 as pb

        statuses = tuple(TicketStatus(s) for s in request.statuses) if request.statuses else ()
        query = TicketListQuery(
            statuses=statuses, created_by=request.created_by or None,
            assigned_to=request.assigned_to or None, unassigned_only=request.unassigned_only,
            related_receipt_id=request.related_receipt_id or None, limit=request.limit or 100,
        )
        result = self._store.list_tickets(request.session_id, query)
        response = pb.ListTicketsResponse(error_code=result.error_code, error_detail=result.error_detail)
        for ticket in result.tickets:
            response.tickets.append(_ticket_to_pb(pb, ticket))
        return response


async def serve(address: str = DEFAULT_ADDRESS, *, store: TicketStore | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import support_ticketing_pb2_grpc

    server = grpc.aio.server()
    support_ticketing_pb2_grpc.add_SupportTicketingServiceServicer_to_server(
        SupportTicketingServicer(store), server
    )
    server.add_insecure_port(address)
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = await serve(addr)
        print(f"listening on {addr}", file=sys.stderr)
        await srv.wait_for_termination()

    asyncio.run(_main())

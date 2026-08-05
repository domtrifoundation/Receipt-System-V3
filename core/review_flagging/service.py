"""The `ReviewFlaggingServicer` gRPC servicer (`review_flagging.proto`) — the real
assembly point wiring `lifecycle.FlagStore` (create/assign/resolve/dismiss/list) and
`audit_screen.build_audit_view` to the wire surface.

**This was a real, complete gap, not a documented placeholder**: `lifecycle.py`,
`gateways.py`, `db.py`, `contracts.py`, `errors.py`, and `metrics.py` were all real and
independently tested, but there was no `.proto` file, no `service.py`, and no generated
stubs anywhere in this package at all — Accounting Sync's own `NoOpFlagChecker`
(`core/accounting_sync/service.py`) exists specifically because this gap meant nothing
could call Review/Flagging over gRPC to check for an open flag.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from .audit_screen import build_audit_view
from .contracts import (
    AssignFlagRequest,
    AuditView,
    CreateFlagRequest,
    DismissFlagRequest,
    Flag,
    FlagResult,
    FlagStatus,
    ListFlagsQuery,
    ListFlagsResult,
    ResolveFlagRequest,
)
from .lifecycle import FlagStore

DEFAULT_ADDRESS = "127.0.0.1:50081"

__all__ = ["DEFAULT_ADDRESS", "ReviewFlaggingServicer", "serve"]


def _flag_to_pb(pb, flag: Flag):
    msg = pb.FlagInfo(
        flag_id=flag.flag_id, flag_type=flag.flag_type, user_id=flag.user_id,
        receipt_id=flag.receipt_id, status=flag.status.value, created_by=flag.created_by,
        created_at=flag.created_at.isoformat(), assigned_to=flag.assigned_to or "",
        resolved_at=flag.resolved_at.isoformat() if flag.resolved_at else "",
        resolved_by=flag.resolved_by or "", resolution_note=flag.resolution_note,
    )
    msg.payload.update({k: str(v) for k, v in flag.payload.items()})
    return msg


def _flag_response(pb, result: FlagResult):
    response = pb.FlagResponse()
    if result.flag is not None:
        response.flag.CopyFrom(_flag_to_pb(pb, result.flag))
    response.error_code = result.error_code
    response.error_detail = result.error_detail
    return response


def _audit_view_response(pb, view: AuditView):
    response = pb.AuditViewResponse(
        receipt_id=view.receipt_id, trace_available=view.trace_available,
        error_code=view.error_code, error_detail=view.error_detail,
    )
    for entry in view.trace:
        response.trace.append(
            pb.AuditTraceEntryInfo(
                timestamp=entry.timestamp.isoformat(), service=entry.service,
                level=entry.level, message=entry.message, detail=entry.detail,
            )
        )
    for flag in view.flags:
        response.flags.append(_flag_to_pb(pb, flag))
    return response


def _list_flags_response(pb, result: ListFlagsResult):
    response = pb.ListFlagsResponse(
        total_matching=result.total_matching, error_code=result.error_code,
        error_detail=result.error_detail,
    )
    for flag in result.flags:
        response.flags.append(_flag_to_pb(pb, flag))
    return response


class ReviewFlaggingServicer:
    """Implements `ReviewFlaggingService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(self, store: FlagStore | None = None) -> None:
        self._store = store if store is not None else FlagStore()

    async def CreateFlag(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import review_flagging_pb2 as pb

        result = await self._store.create_flag(
            CreateFlagRequest(
                flag_type=request.flag_type, user_id=request.user_id,
                receipt_id=request.receipt_id, created_by=request.created_by,
                payload=FrozenDict(dict(request.payload)),
            )
        )
        return _flag_response(pb, result)

    async def AssignFlag(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import review_flagging_pb2 as pb

        result = await self._store.assign_flag(
            AssignFlagRequest(flag_id=request.flag_id, assignee_user_id=request.assignee_user_id),
            request.session_id,
        )
        return _flag_response(pb, result)

    async def ResolveFlag(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import review_flagging_pb2 as pb

        result = await self._store.resolve_flag(
            ResolveFlagRequest(
                flag_id=request.flag_id, resolution_note=request.resolution_note,
                edit_field=request.edit_field or None,
                edit_new_value=request.edit_new_value or None,
            ),
            request.session_id,
        )
        return _flag_response(pb, result)

    async def DismissFlag(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import review_flagging_pb2 as pb

        result = await self._store.dismiss_flag(
            DismissFlagRequest(flag_id=request.flag_id, reason=request.reason),
            request.session_id,
        )
        return _flag_response(pb, result)

    async def GetAuditView(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import review_flagging_pb2 as pb

        view = await build_audit_view(request.receipt_id, self._store)
        return _audit_view_response(pb, view)

    async def ListFlags(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import review_flagging_pb2 as pb

        statuses = tuple(FlagStatus(s) for s in request.statuses) if request.statuses else ()
        result = await self._store.list_flags(
            ListFlagsQuery(
                statuses=statuses, flag_type=request.flag_type or None,
                receipt_id=request.receipt_id or None, assigned_to=request.assigned_to or None,
                limit=request.limit or 100, offset=request.offset,
            )
        )
        return _list_flags_response(pb, result)


async def serve(address: str = DEFAULT_ADDRESS):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import review_flagging_pb2_grpc

    server = grpc.aio.server()
    review_flagging_pb2_grpc.add_ReviewFlaggingServiceServicer_to_server(
        ReviewFlaggingServicer(), server
    )
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = await serve(addr)
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('review_flagging')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())

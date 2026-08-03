"""The per-receipt audit screen (`v3-deepdive-25-review-flagging-api.md` §3) — a workflow
layer over Logs API, never a second store: this pulls the relevant slice of Logs' own data
(how a receipt was scanned, the different OCR engine readings, what Inference concluded
and why it flagged something) into a readable, structured view, alongside every flag this
package has ever raised for the receipt.

**Logs' own `Query` RPC has no `receipt_id` filter — a real, structural limitation, not an
oversight in this module.** `logs.proto`'s `LogQueryRequest` filters by `run_id`/`user_id`/
`service`/`since`/`until` only. `GrpcLogsTraceSource` queries Logs scoped to the receipt's
own `user_id` (resolved here from the flags already found for the receipt, since that is
the only place this package already knows it) and filters the returned stream client-side
for entries whose `context_json` names this receipt id. This is a real query against a
real running Logs service, not a stub — but it is an O(that user's whole log volume) scan,
not an indexed lookup, and a genuinely receipt_id-indexed Logs query would need a new field
on `LogQueryRequest` this session did not add (out of scope for this pass: changing
`logs.proto` is Logs API's own change to make, with its own review).
"""

from __future__ import annotations

from datetime import datetime, timezone

from .contracts import AuditTraceEntry, AuditTraceSource, AuditView, ListFlagsQuery

DEFAULT_LOGS_ADDRESS = "127.0.0.1:50058"


def _parse_timestamp(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)


class GrpcLogsTraceSource:
    """Implements `contracts.AuditTraceSource` against the real `LogsService.Query`
    (`core/logs/logs.proto`, `core/logs/generated/` exists and is reachable).

    Bound to one `user_id` at construction — `AuditTraceSource.fetch()`'s own contract
    takes only `receipt_id` (`contracts.py`), and Logs' own cross-user permission check
    (§4) needs a `user_id` to scope the read to. `build_audit_view()` resolves that
    `user_id` from the flags it already has for the receipt and constructs one of these
    per call, rather than this class guessing at "all users" (`logs.proto`'s own comment:
    empty `user_id` means a cross-user read, gated the same way).
    """

    def __init__(self, user_id: str = "", address: str = DEFAULT_LOGS_ADDRESS, channel=None) -> None:
        self._user_id = user_id
        self._address = address
        self._channel = channel
        self._last_reachable = True

    def _get_channel(self):
        import grpc

        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._address)
        return self._channel

    async def is_available(self) -> bool:
        """Not part of `AuditTraceSource` itself — `build_audit_view()` checks for this
        method via `getattr` after calling `fetch()`, since the Protocol's own `fetch()`
        never raises (§4.4) and needs a separate signal to distinguish "genuinely no
        matching entries" from "the last call could not reach Logs at all"."""
        return self._last_reachable

    async def fetch(self, receipt_id: str) -> tuple[AuditTraceEntry, ...]:
        import grpc

        from core.logs.generated import logs_pb2 as pb
        from core.logs.generated import logs_pb2_grpc as pb_grpc

        stub = pb_grpc.LogsServiceStub(self._get_channel())
        entries: list[AuditTraceEntry] = []
        try:
            async for record in stub.Query(
                pb.LogQueryRequest(user_id=self._user_id, requesting_user_id=self._user_id)
            ):
                if record.error.error_code:
                    self._last_reachable = False
                    break
                entry = record.entry
                if receipt_id and receipt_id not in entry.context_json:
                    continue
                entries.append(
                    AuditTraceEntry(
                        timestamp=_parse_timestamp(entry.timestamp), service=entry.service,
                        level=entry.level, message=entry.message,
                        detail=entry.traceback or entry.context_json,
                    )
                )
            else:
                self._last_reachable = True
        except grpc.RpcError:
            self._last_reachable = False
            return ()
        return tuple(entries)


async def build_audit_view(receipt_id: str, flag_store, trace_source: AuditTraceSource | None = None) -> AuditView:
    """§3's per-receipt audit screen: Logs' own trace, plus every flag this package has
    ever raised for the receipt, in one readable view. Never re-implements or duplicates
    Logs' own storage — purely a query + presentation layer, per the deep-dive's own
    docstring for this function."""
    flags_result = await flag_store.list_flags(ListFlagsQuery(receipt_id=receipt_id))
    flags = flags_result.flags if flags_result.ok else ()
    flag_store.metrics.increment("audit_views_built")

    if trace_source is None:
        resolved_user_id = flags[0].user_id if flags else ""
        trace_source = GrpcLogsTraceSource(user_id=resolved_user_id)

    trace = await trace_source.fetch(receipt_id)
    is_available = getattr(trace_source, "is_available", None)
    trace_available = await is_available() if is_available is not None else True
    if not trace_available:
        flag_store.metrics.increment("audit_trace_unavailable")

    return AuditView(receipt_id=receipt_id, trace=trace, flags=flags, trace_available=trace_available)


__all__ = ["DEFAULT_LOGS_ADDRESS", "GrpcLogsTraceSource", "build_audit_view"]

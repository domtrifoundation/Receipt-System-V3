"""The `AuditService` gRPC servicer — thin by design (deep-dive §2's own layout note).

Every real decision lives in `writer.py`, `query.py`, `retention.py` and `metrics.py`. This
file translates protobuf messages to and from `contracts.py` types and nothing else, which
is what keeps the append-only guarantee a property of the package rather than of this one
file: there is no RPC here that could modify a row even if this file were written carelessly,
because no module underneath it exposes a way to.

**Role resolution fails closed.** §4 requires audit history to be staff/owner only, resolved
from the caller's own session server-side rather than from a role the caller asserts about
itself. Auth & Tenancy owns session resolution and does not exist yet, so `role_resolver` is
injected — and its default denies. That is deliberate: an unresolvable role is denied, never
defaulted to permitted (`docs/PRINCIPLES.md` §4.2). Wiring Auth in later means passing a real
resolver, not removing a permissive default someone forgot about.

**Concurrency**: `grpc.aio`, matching §6's classification of this API as async local SQLite
I/O with no compute-bound work of its own.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

import grpc

from .contracts import (
    DEFAULT_RETENTION_DAYS,
    ActionType,
    AuditEvent,
    AuditQueryFilter,
    RetentionMode,
)
from .errors import E_INVALID_EVENT, E_ROLE_FORBIDDEN, ERROR_SUMMARIES
from .generated import audit_pb2 as pb
from .generated import audit_pb2_grpc as pb_grpc
from .metrics import AuditMetricsReader
from .query import AuditQuery
from .retention import RetentionPurge, resolve_policy
from .writer import AuditWriter

DEFAULT_ADDRESS = "127.0.0.1:50058"

#: Shown on `RetentionPolicyResponse` so a settings screen renders the real legal context
#: rather than a bare number (§5).
BASELINE_CITATION = (
    "BIR Revenue Regulations No. 17-2013, as amended by RR 5-2014 — accounting records "
    "must be preserved for ten (10) years."
)

#: The default resolver. Denies everything, on purpose — see the module docstring.
RoleResolver = Callable[[grpc.ServicerContext], "str | None"]


def deny_all_roles(context) -> str | None:
    return None


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


class _BadTimestamp(Exception):
    """A wire timestamp this build cannot parse. Caught in every RPC that parses one and
    turned into `error_code`/`error_detail` — `datetime.fromisoformat` raising `ValueError`
    straight out of a servicer method would be an exception crossing the gRPC boundary,
    which is the one thing `docs/PRINCIPLES.md` §4.1 rules out here."""

    def __init__(self, field: str, value: str) -> None:
        super().__init__(f"{field} is not a valid ISO-8601 timestamp: {value!r}")


def _parse_iso(value: str, field: str = "timestamp") -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise _BadTimestamp(field, value) from exc


def _to_message(event: AuditEvent) -> pb.AuditEventMessage:
    return pb.AuditEventMessage(
        event_id=event.event_id,
        action_type=event.action_type.value,
        actor_user_id=event.actor_user_id,
        target_user_id=event.target_user_id or "",
        reason=event.reason or "",
        details_json=json.dumps(dict(event.details), default=str, sort_keys=True),
        occurred_at=_iso(event.occurred_at),
        corrects_event_id=event.corrects_event_id or "",
    )


class AuditServicer(pb_grpc.AuditServiceServicer):
    def __init__(
        self,
        db_path: Path | str | None = None,
        writer: AuditWriter | None = None,
        role_resolver: RoleResolver = deny_all_roles,
    ) -> None:
        self._writer = writer or AuditWriter(db_path)
        self._query = AuditQuery(db_path)
        self._retention = RetentionPurge(db_path)
        self._metrics = AuditMetricsReader(db_path)
        self._role_resolver = role_resolver

    # ------------------------------------------------------------------ write
    async def RecordAction(self, request, context):
        details = None
        if request.details_json:
            try:
                parsed = json.loads(request.details_json)
            except json.JSONDecodeError as exc:
                return pb.RecordActionResponse(
                    recorded=False, error_code=E_INVALID_EVENT, error_detail=str(exc)
                )
            if not isinstance(parsed, dict):
                return pb.RecordActionResponse(
                    recorded=False,
                    error_code=E_INVALID_EVENT,
                    error_detail="details_json must be a JSON object",
                )
            details = parsed

        try:
            occurred_at = _parse_iso(request.occurred_at, "occurred_at")
        except _BadTimestamp as exc:
            return pb.RecordActionResponse(
                recorded=False, error_code=E_INVALID_EVENT, error_detail=str(exc)
            )

        result = await self._writer.record_action(
            request.operation,
            request.actor_user_id,
            target_user_id=request.target_user_id or None,
            reason=request.reason or None,
            details=details,
            corrects_event_id=request.corrects_event_id or None,
            occurred_at=occurred_at,
        )
        return pb.RecordActionResponse(
            recorded=result.recorded,
            event_id=result.event_id or "",
            degraded_sinks=list(result.degraded_sinks),
            error_code=result.error or "",
            error_detail=result.error_detail or "",
        )

    # ------------------------------------------------------------------- read
    async def QueryEvents(self, request, context):
        role = self._role_resolver(context)
        try:
            action_types = tuple(ActionType(a) for a in request.action_types)
            occurred_after = _parse_iso(request.occurred_after, "occurred_after")
            occurred_before = _parse_iso(request.occurred_before, "occurred_before")
        except (ValueError, _BadTimestamp) as exc:
            return pb.QueryEventsResponse(error_code=E_INVALID_EVENT, error_detail=str(exc))

        result = await self._query.fetch(
            AuditQueryFilter(
                action_types=action_types,
                actor_user_id=request.actor_user_id or None,
                target_user_id=request.target_user_id or None,
                occurred_after=occurred_after,
                occurred_before=occurred_before,
                limit=request.limit or 100,
                offset=request.offset,
            ),
            role,
        )
        return pb.QueryEventsResponse(
            events=[_to_message(e) for e in result.events],
            total_matching=result.total_matching,
            error_code=result.error or "",
            error_detail=result.error_detail or "",
        )

    async def GetEvent(self, request, context):
        role = self._role_resolver(context)
        result = await self._query.get(request.event_id, role)
        return pb.QueryEventsResponse(
            events=[_to_message(e) for e in result.events],
            total_matching=result.total_matching,
            error_code=result.error or "",
            error_detail=result.error_detail or "",
        )

    # -------------------------------------------------------------- retention
    async def ResolveRetentionPolicy(self, request, context):
        resolution = resolve_policy(
            request.retention_days or None,
            request.retention_mode or RetentionMode.FIXED,
            shorten_override=request.shorten_override,
            shorten_override_reason=request.shorten_override_reason or None,
        )
        if resolution.error or resolution.policy is None:
            return pb.RetentionPolicyResponse(
                baseline_citation=BASELINE_CITATION,
                error_code=resolution.error or "",
                error_detail=resolution.error_detail or "",
            )
        p = resolution.policy
        return pb.RetentionPolicyResponse(
            retention_days=p.retention_days,
            retention_mode=p.mode.value,
            shorten_override=p.shorten_override,
            shorten_override_reason=p.shorten_override_reason or "",
            baseline_citation=BASELINE_CITATION,
        )

    async def ApplyRetentionPolicy(self, request, context):
        # Applying a policy deletes records, so it is owner/staff-gated the same way reading
        # is — and gated before anything is resolved, not after.
        role = self._role_resolver(context)
        from .query import role_permitted

        if not role_permitted(role):
            return pb.ApplyRetentionPolicyResponse(
                error_code=E_ROLE_FORBIDDEN, error_detail=ERROR_SUMMARIES[E_ROLE_FORBIDDEN]
            )
        resolution = resolve_policy(
            request.retention_days or None,
            request.retention_mode or RetentionMode.FIXED,
            shorten_override=request.shorten_override,
            shorten_override_reason=request.shorten_override_reason or None,
        )
        if resolution.error or resolution.policy is None:
            return pb.ApplyRetentionPolicyResponse(
                error_code=resolution.error or "", error_detail=resolution.error_detail or ""
            )
        result = await self._retention.purge(
            resolution.policy, request.actor_user_id or "system"
        )
        return pb.ApplyRetentionPolicyResponse(
            purged=result.purged,
            horizon=_iso(result.horizon),
            error_code=result.error or "",
            error_detail=result.error_detail or "",
        )

    # ---------------------------------------------------------------- metrics
    async def GetMetrics(self, request, context):
        resolution = resolve_policy(
            request.retention_days or DEFAULT_RETENTION_DAYS,
            request.retention_mode or RetentionMode.FIXED,
        )
        # An unresolvable retention policy must not be dropped on the floor: without this the
        # response would come back with `events_past_horizon == 0` and no error, telling a
        # monitoring caller "nothing is waiting for the next sweep" when the truth is "your
        # retention setting could not be resolved at all". The counts that do not depend on a
        # horizon are still returned — degrade, but never silently (§4.3, §4.4).
        snapshot = await self._metrics.snapshot(resolution.policy)
        return pb.MetricsResponse(
            total_events=snapshot.total_events,
            events_by_action=dict(snapshot.events_by_action),
            oldest_occurred_at=_iso(snapshot.oldest_occurred_at),
            newest_occurred_at=_iso(snapshot.newest_occurred_at),
            events_past_horizon=snapshot.events_past_horizon,
            database_bytes=snapshot.database_bytes,
            error_code=snapshot.error or resolution.error or "",
            error_detail=snapshot.error_detail or resolution.error_detail or "",
        )

    def close(self) -> None:
        self._writer.close()
        self._query.close()
        self._retention.close()
        self._metrics.close()


async def serve(
    address: str = DEFAULT_ADDRESS,
    db_path: Path | str | None = None,
    role_resolver: RoleResolver = deny_all_roles,
) -> grpc.aio.Server:
    """Start the service and return the running server so a caller can stop it.

    Pass a `:0` port to bind an ephemeral one; the actually-bound address is attached as
    `bound_address`. Worth having rather than hard-coding: Windows reserves scattered ranges
    in the 50000s, so a fixed high port is not reliably bindable across machines.
    """
    server = grpc.aio.server()
    pb_grpc.add_AuditServiceServicer_to_server(
        AuditServicer(db_path, role_resolver=role_resolver), server
    )
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
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
        print(f"AuditService listening on {srv.bound_address}", file=sys.stderr)
        # The resolved interpreter, not just a launch message — this is what makes
        # `PYTHON_BIN=... ./start.sh` independently verifiable from outside the process.
        print(f"running under: {sys.executable} ({sys.version.split()[0]})", file=sys.stderr)
        await srv.wait_for_termination()

    asyncio.run(_main())

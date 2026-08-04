"""The `NotificationsService` gRPC servicer — thin by design (matching `core/logs/service.py`
and `core/audit/service.py`'s own "translation layer only" discipline).

Every real decision lives in `inbox.py` (in-app storage + the cross-user gate), `dispatch.py`
(fan-out + bounded retry), and `preferences.py`. This file translates protobuf messages to and
from `contracts.py` types and nothing else — there is no RPC here that could read a second
user's inbox even if this file were written carelessly, because the identity resolved for
every RPC comes from `_session_resolver`, never from a wire field.

**Session resolution is the one place this package is *stricter* than Logs' own precedent.**
`core/logs/service.py`'s `to_query` reads `request.requesting_user_id` straight off the wire —
acceptable there because that field is documented as populated by a trusted upstream hop, but
this package's own task explicitly calls for resolving identity server-side and never trusting
a caller-asserted id. So: `notifications.proto` has no `requesting_user_id` field anywhere
(see the `.proto`'s own header comment), and every RPC below resolves the caller through
`_session_resolver(context)` — a session id read from gRPC metadata, evaluated against Auth.
**The default resolver denies everything** (`deny_all_sessions`), the same fail-closed default
`core/audit/service.py::deny_all_roles` uses for role resolution (`docs/PRINCIPLES.md` §4.2):
an inbox process running before Auth is reachable serves nothing cross-session, which is
correct behaviour, not a degraded one.

**Concurrency**: `grpc.aio`, matching `dispatch.Notifier.notify`'s own `async def` shape —
outbound channel sends are genuine network I/O (deep-dive §6), the same bucket
`core/audit/service.py` already uses for its own async local-SQLite-I/O RPCs.

The generated stubs are imported lazily inside each method and inside `serve()`, exactly as
`core/logs/service.py` and `core/health/service.py` do, so this package stays importable — and
its tests meaningful — on an interpreter with no `grpcio` wheel yet (`docs/MAINTENANCE.md` §3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from .contracts import InboxQuery, NotifyRequest
from .dispatch import Notifier
from .errors import E_SESSION_UNRESOLVABLE, ERROR_SUMMARIES
from .inbox import InboxStore
from .metrics import NotificationsMetricsCollector
from .preferences import PreferenceStore

DEFAULT_ADDRESS = "127.0.0.1:50063"

#: `context -> user_id | None`. The one seam this file needs onto Auth & Tenancy — see the
#: module docstring for why the default denies everything rather than trusting the wire.
SessionResolverFn = Callable[[object], "str | None"]


def deny_all_sessions(context) -> str | None:
    """The fail-closed default. See the module docstring."""
    return None


def session_id_from_context(context) -> str | None:
    """The session id a real interceptor/cookie bridge would have attached as gRPC metadata.

    Returns `None` for a missing context or a missing key rather than raising — an absent
    session id is exactly the ordinary "caller is not authenticated" case, not a transport
    failure worth its own exception.
    """
    if context is None:
        return None
    getter = getattr(context, "invocation_metadata", None)
    if getter is None:
        return None
    try:
        metadata = dict(getter())
    except Exception:  # noqa: BLE001 - a malformed metadata iterable is "no session", not a crash
        return None
    return metadata.get("session_id") or None


class AuthSessionResolver:
    """Adapts Auth's own session validation without importing Auth (`docs/PRINCIPLES.md`
    §1.3) — the identical adapter shape as `core/logs/query.py::AuthBreakGlassChecker` and
    `core/audit/service.py`'s own `role_resolver`. `validate` is injected: a callable taking a
    session id and returning a user id, or raising/returning `None` if it cannot. When Auth's
    real gRPC client exists, this is the one file that changes."""

    def __init__(self, validate: Callable[[str], "str | None"]) -> None:
        self._validate = validate

    def __call__(self, context) -> str | None:
        session_id = session_id_from_context(context)
        if not session_id:
            return None
        try:
            return self._validate(session_id)
        except Exception:  # noqa: BLE001 - "cannot resolve" is denial, never a crash here
            return None


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _notification_to_wire(notification, pb):
    return pb.NotificationMessage(
        notification_id=notification.notification_id,
        user_id=notification.user_id,
        category=notification.category,
        title=notification.title,
        body=notification.body,
        reference=notification.reference or "",
        read_at=_iso(notification.read_at),
        created_at=_iso(notification.created_at),
    )


def _status_to_wire(status, pb):
    return pb.DeliveryStatusMessage(
        channel=status.channel,
        outcome=status.outcome.value,
        attempt=status.attempt,
        error_detail=status.error_detail,
        delivered_at=_iso(status.delivered_at),
    )


def _preference_to_wire(preference, pb):
    return pb.ChannelPreferenceMessage(
        channel=preference.channel,
        enabled=preference.enabled,
        contact_override=preference.contact_override or "",
    )


class NotificationsServicer:
    """Implements `NotificationsService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        *,
        inbox: InboxStore | None = None,
        preferences: PreferenceStore | None = None,
        notifier: Notifier | None = None,
        session_resolver: SessionResolverFn = deny_all_sessions,
        metrics: NotificationsMetricsCollector | None = None,
    ) -> None:
        self._metrics = metrics or NotificationsMetricsCollector()
        self._inbox = inbox or InboxStore(metrics=self._metrics)
        self._preferences = preferences or PreferenceStore()
        self._notifier = notifier or Notifier(
            self._inbox, self._preferences, metrics=self._metrics
        )
        self._session_resolver = session_resolver

    # ------------------------------------------------------------------ write
    async def Notify(self, request, context):  # noqa: N802 - gRPC method naming
        from .generated import notifications_pb2 as pb

        result = await self._notifier.notify(
            NotifyRequest(
                user_id=request.user_id,
                category=request.category,
                title=request.title,
                body=request.body,
                reference=request.reference or None,
            )
        )
        return pb.NotifyResponse(
            ok=result.ok,
            notification=(
                _notification_to_wire(result.notification, pb)
                if result.notification is not None
                else None
            ),
            channel_statuses=[_status_to_wire(s, pb) for s in result.channel_statuses],
            error_code=result.error_code,
            error_detail=result.error_detail,
        )

    # ------------------------------------------------------------------- read
    async def QueryInbox(self, request, context):  # noqa: N802
        from .generated import notifications_pb2 as pb

        requester = self._session_resolver(context)
        result = self._inbox.query(
            InboxQuery(
                user_id=request.user_id,
                requesting_user_id=requester,
                unread_only=request.unread_only,
                limit=request.limit or 100,
                offset=request.offset,
            )
        )
        return pb.QueryInboxResponse(
            notifications=[_notification_to_wire(n, pb) for n in result.notifications],
            total_matching=result.total_matching,
            error_code=result.error_code,
            error_detail=result.error_detail,
        )

    async def MarkRead(self, request, context):  # noqa: N802
        from .generated import notifications_pb2 as pb

        requester = self._session_resolver(context)
        result = self._inbox.mark_read(requester, request.notification_id)
        return pb.MarkReadResponse(
            ok=result.ok,
            notification_id=result.notification_id,
            error_code=result.error_code,
            error_detail=result.error_detail,
        )

    # ------------------------------------------------------------- preferences
    async def GetPreferences(self, request, context):  # noqa: N802
        from .generated import notifications_pb2 as pb

        requester = self._session_resolver(context)
        if requester is None:
            return pb.GetPreferencesResponse(
                error_code=E_SESSION_UNRESOLVABLE,
                error_detail=ERROR_SUMMARIES[E_SESSION_UNRESOLVABLE],
            )
        result = self._preferences.get_all(requester)
        return pb.GetPreferencesResponse(
            preferences=[_preference_to_wire(p, pb) for p in result.preferences],
            error_code=result.error_code,
            error_detail=result.error_detail,
        )

    async def SetPreference(self, request, context):  # noqa: N802
        from .generated import notifications_pb2 as pb

        requester = self._session_resolver(context)
        if requester is None:
            return pb.SetPreferenceResponse(
                ok=False,
                error_code=E_SESSION_UNRESOLVABLE,
                error_detail=ERROR_SUMMARIES[E_SESSION_UNRESOLVABLE],
            )
        result = self._preferences.set(
            requester, request.channel, request.enabled, request.contact_override or None
        )
        return pb.SetPreferenceResponse(
            ok=result.ok,
            preference=(
                _preference_to_wire(result.preference, pb)
                if result.preference is not None
                else None
            ),
            error_code=result.error_code,
            error_detail=result.error_detail,
        )

    def close(self) -> None:
        self._inbox.close()
        self._preferences.close()


async def serve(
    address: str = DEFAULT_ADDRESS,
    *,
    session_resolver: SessionResolverFn = deny_all_sessions,
    top_level=None,
):
    """Start the service and return the running server so a caller can stop it.

    Pass a `:0` port to bind an ephemeral one; the actually-bound address is attached as
    `bound_address`. Windows reserves scattered ranges in the 50000s, so a fixed high port is
    not reliably bindable across machines (the same note every other `serve()` in this
    project's Core APIs carries).
    """
    import grpc

    from .generated import notifications_pb2_grpc as pb_grpc

    metrics = NotificationsMetricsCollector()
    inbox = InboxStore(top_level, metrics=metrics)
    preferences = PreferenceStore(top_level)
    servicer = NotificationsServicer(
        inbox=inbox,
        preferences=preferences,
        notifier=Notifier(inbox, preferences, metrics=metrics),
        session_resolver=session_resolver,
        metrics=metrics,
    )

    server = grpc.aio.server()
    pb_grpc.add_NotificationsServiceServicer_to_server(servicer, server)
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
        print(f"NotificationsService listening on {srv.bound_address}", file=sys.stderr)
        print(f"running under: {sys.executable} ({sys.version.split()[0]})", file=sys.stderr)
        await srv.wait_for_termination()

    asyncio.run(_main())


__all__ = [
    "DEFAULT_ADDRESS",
    "AuthSessionResolver",
    "NotificationsServicer",
    "deny_all_sessions",
    "serve",
    "session_id_from_context",
]

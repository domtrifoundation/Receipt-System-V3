"""The real Auth adapter `permission_gate.py`'s own `SessionResolver` Protocol names but
leaves unimplemented — a genuine, previously-undiscovered gap: `service.py`'s own
`__main__` called `serve(addr)` with no `resolver` at all, which means `PermissionGate`
defaulted to `DenyAllSessions()` — **the real, deployed Groups service denied every
gated call it ever received**, confirmed by direct inspection, not assumed. This client
is what makes it actually work.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.auth.contracts import Role, Session

__all__ = ["GrpcSessionResolver"]

DEFAULT_AUTH_ADDRESS = "127.0.0.1:50056"


class GrpcSessionResolver:
    """Implements `permission_gate.SessionResolver` for real, against Auth's own
    `ValidateSession` RPC. Never raises — every failure mode (expired, revoked, unknown,
    Auth itself unreachable) collapses to `None`, matching the Protocol's own contract."""

    def __init__(self, address: str = DEFAULT_AUTH_ADDRESS) -> None:
        self._address = address

    async def resolve(self, session_id: str) -> Session | None:
        import grpc

        from core.auth.generated import auth_pb2 as pb
        from core.auth.generated import auth_pb2_grpc as pb_grpc

        try:
            async with grpc.aio.insecure_channel(self._address) as channel:
                response = await pb_grpc.AuthServiceStub(channel).ValidateSession(
                    pb.ValidateSessionRequest(session_id=session_id)
                )
        except grpc.aio.AioRpcError:
            return None
        if response.error_code or not response.session_id:
            return None

        now = datetime.now(timezone.utc)
        return Session(
            session_id=response.session_id, user_id=response.user_id,
            role=Role(response.role), created_at=now, last_seen_at=now,
            expires_at=datetime.fromtimestamp(response.expires_at_unix, tz=timezone.utc),
        )

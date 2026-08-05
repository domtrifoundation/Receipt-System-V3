"""A thin gRPC client for Health API's live VRAM reservation ledger (deep-dive §5.6,
`core/health/resource_ledger.py`'s own module docstring: "OCR ... check in here before
claiming GPU resources. This module is the thing those three documents were promised.").

**A rejection is a normal answer, not an error** (Health's own §5.1) — every caller here
treats a rejected/unreachable reservation the same way: fall back to CPU, never fail the
engine. This is the opposite posture from `content_security_client.py`'s fail-closed
guarantee, and deliberately so — a missing malware scan is a security gap, a missing GPU
reservation is a performance degradation.

**Setup API's `HardwareProfile` is not published yet** (`core/health/resource_ledger.py`'s
own docstring: "Setup does not exist yet, so the default reader publishes nothing and
every reservation against an unknown device is rejected"), so every real reservation
attempt through this client currently comes back `UNKNOWN_DEVICE` — confirmed live against
a real, running Health service, not assumed. That is exactly the correct, honest state:
the integration point exists and is exercised for real; what it needs from Setup API to
ever grant a GPU reservation is a separate, already-tracked dependency, not something this
client fakes around.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["HealthClient", "ReservationResult"]

DEFAULT_HEALTH_ADDRESS = "127.0.0.1:50061"


@dataclass(frozen=True)
class ReservationResult:
    granted: bool
    reservation_id: str = ""
    rejection_reason: str = ""


class HealthClient:
    def __init__(self, address: str = DEFAULT_HEALTH_ADDRESS, timeout_seconds: float = 5.0) -> None:
        self._address = address
        self._timeout_seconds = timeout_seconds

    async def reserve(self, owning_api: str, device_id: str, mb: int) -> ReservationResult:
        """Never raises — an unreachable Health service or a rejected reservation both
        come back as `granted=False`, the caller's own cue to fall back to CPU."""
        try:
            import grpc

            from core.health.generated import health_pb2 as pb
            from core.health.generated import health_pb2_grpc as pb_grpc
        except ImportError:
            return ReservationResult(granted=False, rejection_reason="health_client_unavailable")

        try:
            async with grpc.aio.insecure_channel(self._address) as channel:
                stub = pb_grpc.HealthServiceStub(channel)
                response = await stub.ReserveResource(
                    pb.ReserveRequest(owning_api=owning_api, device_id=device_id, requested_mb=mb),
                    timeout=self._timeout_seconds,
                )
        except Exception:  # noqa: BLE001 - unreachable/timeout falls back to CPU, never raises
            return ReservationResult(granted=False, rejection_reason="health_service_unreachable")

        if not response.granted:
            return ReservationResult(granted=False, rejection_reason=response.rejection_reason)
        return ReservationResult(granted=True, reservation_id=response.reservation.reservation_id)

    async def release(self, reservation_id: str, reason: str = "released") -> bool:
        """Best-effort — a failure to release is logged elsewhere (metrics), never raised;
        Health's own TTL sweep (`resource_ledger.py`'s §5.2) is the backstop for a release
        call that never arrives at all (a crashed engine process, say)."""
        if not reservation_id:
            return False
        try:
            import grpc

            from core.health.generated import health_pb2 as pb
            from core.health.generated import health_pb2_grpc as pb_grpc
        except ImportError:
            return False

        try:
            async with grpc.aio.insecure_channel(self._address) as channel:
                stub = pb_grpc.HealthServiceStub(channel)
                response = await stub.ReleaseResource(
                    pb.ReleaseRequest(reservation_id=reservation_id, reason=reason),
                    timeout=self._timeout_seconds,
                )
                return bool(response.released)
        except Exception:  # noqa: BLE001 - best-effort, see docstring
            return False

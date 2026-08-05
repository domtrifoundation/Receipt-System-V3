"""A thin gRPC client for Health API's live VRAM reservation ledger (deep-dive §8.6,
`core/health/resource_ledger.py`'s own module docstring: "Inference (§8.6) ... check in
here before claiming GPU resources. This module is the thing those three documents were
promised."). Identical shape to `core/ocr/health_client.py` — deliberately a separate
module, not a shared import, since a Protocol seam per package (`docs/PRINCIPLES.md`
§1.3) is this project's own standing convention for this exact situation, not an
oversight to collapse into one shared client.

**A rejection is a normal answer, not an error** (Health's own §5.1) — a rejected/
unreachable reservation means fall back to CPU, never fail generation.

**Setup API's `HardwareProfile` is not published yet**, so every real reservation attempt
through this client currently comes back `UNKNOWN_DEVICE` — confirmed live against a real,
running Health service (see `core/ocr/health_client.py`'s own module docstring for the
same confirmed state; both clients hit the identical, real, unpublished-profile answer).
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

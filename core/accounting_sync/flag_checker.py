"""A real `FlagChecker` (`contracts.py`) against Review/Flagging's now-real gRPC surface.

**This closes a gap this package's own `service.py`/`CLAUDE.md` previously documented as
structurally unfixable**: Review/Flagging had no `.proto`/`service.py`/generated stubs at
all, so `NoOpFlagChecker` was the only option. `core/review_flagging/service.py` and
`review_flagging.proto` now exist (a separate session pass), and `GrpcFlagChecker` is the
real client against `ReviewFlaggingService.ListFlags`, filtered to the two non-terminal
statuses (`open`, `assigned`) per `FlagChecker.has_open_flag`'s own contract.

`AccountingSyncServicer`'s own `flag_checker` constructor parameter still defaults to
`NoOpFlagChecker` (`service.py`) — swapping the default is a deliberate deployment
decision, not something this module does unilaterally, since a real deployment needs
Review/Flagging's own address configured correctly first.
"""

from __future__ import annotations

__all__ = ["GrpcFlagChecker"]

DEFAULT_REVIEW_FLAGGING_ADDRESS = "127.0.0.1:50081"

#: The two `FlagStatus` values that mean "still open" (`core/review_flagging/contracts.py`'s
#: own `FlagStatus.OPEN`/`ASSIGNED`) — `RESOLVED`/`DISMISSED` are terminal and do not block
#: a push.
_OPEN_STATUSES = ("open", "assigned")


class GrpcFlagChecker:
    def __init__(self, address: str = DEFAULT_REVIEW_FLAGGING_ADDRESS, timeout_seconds: float = 5.0) -> None:
        self._address = address
        self._timeout_seconds = timeout_seconds

    async def has_open_flag(self, receipt_id: str) -> bool:
        """Fails **open** (reports no flag) on an unreachable Review/Flagging service —
        deliberately the opposite of `content_security_client.py`'s fail-closed posture,
        because a missing flag check here is a data-correctness risk, not a security gap
        (the same distinction `core/ocr/health_client.py`'s own docstring draws for its
        GPU-reservation check). A real deployment that cannot reach Review/Flagging at all
        has bigger problems than one unconfirmed push; blocking every push in that state
        would be a worse failure mode than the rare bad record this check exists to catch.
        """
        try:
            import grpc

            from core.review_flagging.generated import review_flagging_pb2 as pb
            from core.review_flagging.generated import review_flagging_pb2_grpc as pb_grpc
        except ImportError:
            return False

        try:
            async with grpc.aio.insecure_channel(self._address) as channel:
                stub = pb_grpc.ReviewFlaggingServiceStub(channel)
                response = await stub.ListFlags(
                    pb.ListFlagsRequest(receipt_id=receipt_id, statuses=list(_OPEN_STATUSES), limit=1),
                    timeout=self._timeout_seconds,
                )
        except Exception:  # noqa: BLE001 - unreachable/timeout fails open, see docstring
            return False

        if response.error_code:
            return False
        return len(response.flags) > 0

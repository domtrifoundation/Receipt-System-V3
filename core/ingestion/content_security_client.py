"""A thin gRPC client for the Content Security API (deep-dive §6) — no scanning logic
here at all, ever; that lives entirely in `core/content_security/`.

**Fail closed, the one deliberate exception to graceful degradation in this package**
(`docs/PRINCIPLES.md` §4.2, `errors.ContentSecurityUnavailable`'s own docstring): an
unreachable service, a timeout, or a malformed response all raise
`ContentSecurityUnavailable` rather than returning "assume safe" — a file that can't be
verified never gets processed just because the verifier was slow to respond.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from common.frozen_dict import FrozenDict

from .errors import ContentSecurityUnavailable

__all__ = ["ContentSecurityClient", "ScanOutcome"]

DEFAULT_CONTENT_SECURITY_ADDRESS = "127.0.0.1:50062"


@dataclass(frozen=True)
class ScanOutcome:
    """This package's own thin mirror of `core/content_security/contracts.ScanVerdict` —
    a separate type, not an import of Content Security's own dataclass, since the wire
    response is what this client actually has in hand (protobuf fields), not that
    package's internal Python type. Keeping the shape deliberately small and matching
    only what Ingestion itself reads (`safe`, `detected_type`) rather than re-exporting
    Content Security's full internal verdict shape."""

    safe: bool
    detected_type: str = ""
    rejection_reason: str = ""
    error_code: str = ""
    provider_verdicts: FrozenDict = field(default_factory=lambda: FrozenDict({}))


class ContentSecurityClient:
    def __init__(
        self, address: str = DEFAULT_CONTENT_SECURITY_ADDRESS, timeout_seconds: float = 15.0
    ) -> None:
        self._address = address
        self._timeout_seconds = timeout_seconds

    async def scan(
        self,
        content: bytes,
        *,
        claimed_mime_type: str = "",
        claimed_filename: str = "",
        blob_ref: str = "",
        requesting_user_id: str = "",
        run_id: str = "",
    ) -> ScanOutcome:
        try:
            import grpc

            from core.content_security.generated import content_security_pb2 as pb
            from core.content_security.generated import content_security_pb2_grpc as pb_grpc
        except ImportError as exc:
            raise ContentSecurityUnavailable(f"grpc/content_security stubs unavailable: {exc}") from exc

        try:
            async with grpc.aio.insecure_channel(self._address) as channel:
                stub = pb_grpc.ContentSecurityServiceStub(channel)
                response = await stub.ScanFile(
                    pb.ScanRequest(
                        content=content,
                        claimed_mime_type=claimed_mime_type,
                        claimed_filename=claimed_filename,
                        blob_ref=blob_ref,
                        requesting_user_id=requesting_user_id,
                        run_id=run_id,
                    ),
                    timeout=self._timeout_seconds,
                )
        except Exception as exc:  # noqa: BLE001 - unreachable/timeout/malformed all fail closed
            raise ContentSecurityUnavailable(f"{type(exc).__name__}: {exc}") from exc

        return ScanOutcome(
            safe=response.safe,
            detected_type=response.detected_type,
            rejection_reason=response.rejection_reason,
            error_code=response.error_code,
            provider_verdicts=FrozenDict(dict(response.provider_verdicts)),
        )

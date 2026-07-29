"""The `MatchingService` gRPC servicer (§7, extended by §5.1's resolved mechanism) — thin by
design.

Every real decision lives in `two_way_match.py`, `vendor_match_context.py`, `fuzzy_match.py`
and `reverse_gazetteer.py`. This file translates protobuf messages to and from the contract
types and nothing else — the same thin-translation discipline `core/health/service.py` and
`core/geo_address/service.py` both state for their own surfaces, and for the identical reason:
`docs/PRINCIPLES.md` §1.9's guarantee is a property of `two_way_match.match_vendor` itself, not
of this file, so Execution Core's synchronous call and Reconciliation's retroactive sweep both
reach the identical function through this identical RPC rather than by each calling some other
in-process shortcut that could quietly drift from it.

**Errors are data** (`docs/PRINCIPLES.md` §4.1): every response carries `error_code`/
`error_detail`; nothing raises across the boundary. An empty candidate list, a zero-scoring
match, and a low top score are all real, honest `MatchResponse`/`MatchContextResponse`
payloads, never an error.

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly as
`core/logs/service.py` and `core/health/service.py` both do, so this package stays importable
— and its tests meaningful — on an interpreter with no `grpcio` wheel yet.
"""

from __future__ import annotations

from concurrent import futures
from collections.abc import Iterable

from .contracts import (
    MatchContext,
    MatchRequest,
    MatchResult,
    VendorCandidate,
    VendorCorroborationPolicy,
    VendorMatchContextRequest,
)
from .metrics import MatchMetricsCollector
from .reverse_gazetteer import reverse_gazetteer_scan
from .two_way_match import match_vendor
from .vendor_match_context import get_vendor_match_context

DEFAULT_ADDRESS = "127.0.0.1:50065"


def _candidate_from_wire(message) -> VendorCandidate:
    entity_kind = message.entity_kind or "corporation"
    return VendorCandidate(
        entity_id=message.entity_id,
        name=message.name,
        entity_kind=entity_kind if entity_kind in ("corporation", "franchiser") else "corporation",
        tin=message.tin,
        category_code=message.category_code or None,
        aliases=tuple(message.aliases),
    )


def _candidates_from_wire(messages: Iterable) -> tuple[VendorCandidate, ...]:
    return tuple(_candidate_from_wire(m) for m in messages)


def to_match_request(request) -> MatchRequest:
    """Wire `MatchRequest` -> contract. `limit`/`plausibility_window` of `0` fall back to the
    contract's own defaults — proto3's zero-value default must not be read as "return nothing"
    or "scan nothing", which is what a literal `0` would otherwise mean."""
    from .contracts import DEFAULT_FORWARD_LIMIT, DEFAULT_PLAUSIBILITY_WINDOW

    return MatchRequest(
        extracted_text=request.extracted_text,
        raw_ocr_text=request.raw_ocr_text,
        candidates=_candidates_from_wire(request.candidates),
        limit=request.limit or DEFAULT_FORWARD_LIMIT,
        plausibility_window=request.plausibility_window or DEFAULT_PLAUSIBILITY_WINDOW,
    )


def _candidate_to_wire(candidate, pb):
    return pb.MatchCandidateProto(
        canonical_name=candidate.canonical_name,
        score=candidate.score,
        source=candidate.source.value if hasattr(candidate.source, "value") else candidate.source,
        entity_id=candidate.entity_id,
        entity_kind=candidate.entity_kind,
        tin=candidate.tin,
        category_code=candidate.category_code or "",
        matched_alias=candidate.matched_alias,
    )


def to_match_response(result: MatchResult, pb):
    if result.error is not None:
        return pb.MatchResponse(error_code=result.error.code, error_detail=result.error.detail)
    return pb.MatchResponse(candidates=[_candidate_to_wire(c, pb) for c in result.candidates])


def to_context_response(context: MatchContext, pb):
    if context.error is not None:
        return pb.MatchContextResponse(
            error_code=context.error.code, error_detail=context.error.detail
        )
    return pb.MatchContextResponse(
        candidates=[_candidate_to_wire(c, pb) for c in context.candidates],
        included=context.included,
        policy=context.policy.value,
        top_score=context.top_score,
    )


class MatchingServicer:
    """Implements `MatchingService`. Registered by name, so importing the generated stubs is
    `serve()`'s business and this class stays importable without them."""

    def __init__(self, *, metrics: MatchMetricsCollector | None = None) -> None:
        self._metrics = metrics or MatchMetricsCollector()

    def MatchVendor(self, request, context):  # noqa: N802 - gRPC method naming
        from .generated import matching_pb2 as pb

        match_request = to_match_request(request)
        result = match_vendor(match_request, metrics=self._metrics)
        return to_match_response(result, pb)

    def ReverseGazetteerScan(self, request, context):  # noqa: N802
        from .contracts import DEFAULT_FORWARD_LIMIT, DEFAULT_PLAUSIBILITY_WINDOW
        from .generated import matching_pb2 as pb

        candidates = _candidates_from_wire(request.candidates)
        found = reverse_gazetteer_scan(
            request.raw_ocr_text,
            candidates,
            plausibility_window=request.plausibility_window or DEFAULT_PLAUSIBILITY_WINDOW,
            limit=request.limit or DEFAULT_FORWARD_LIMIT,
            metrics=self._metrics,
        )
        return pb.MatchResponse(candidates=[_candidate_to_wire(c, pb) for c in found])

    def GetVendorMatchContext(self, request, context):  # noqa: N802
        from .generated import matching_pb2 as pb

        try:
            policy = VendorCorroborationPolicy(request.policy) if request.policy else (
                VendorCorroborationPolicy.ALWAYS
            )
        except ValueError:
            from .errors import InvalidCorroborationPolicy, code_for, summary_for

            exc = InvalidCorroborationPolicy(request.policy)
            code = code_for(exc)
            return pb.MatchContextResponse(error_code=code, error_detail=summary_for(code))

        from .contracts import DEFAULT_BELOW_THRESHOLD_SCORE

        context_request = VendorMatchContextRequest(
            match_request=to_match_request(request.match_request),
            policy=policy,
            threshold=request.threshold or DEFAULT_BELOW_THRESHOLD_SCORE,
        )
        result_context = get_vendor_match_context(context_request, metrics=self._metrics)
        return to_context_response(result_context, pb)


def serve(address: str = DEFAULT_ADDRESS, *, metrics: MatchMetricsCollector | None = None):
    """Start the service. Returns the running server so a caller can stop it.

    Pass a `:0` port to bind an ephemeral one — the actually-bound address is attached to the
    returned server as `bound_address`. Windows reserves scattered ranges in the 50000s, so a
    fixed high port is not reliably bindable across machines.
    """
    import grpc

    from .generated import matching_pb2_grpc as pb_grpc

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_MatchingServiceServicer_to_server(MatchingServicer(metrics=metrics), server)
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import sys

    addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
    srv = serve(addr)
    print(f"MatchingService listening on {addr}", file=sys.stderr)
    print(f"running under: {sys.executable} ({sys.version.split()[0]})", file=sys.stderr)
    srv.wait_for_termination()


__all__ = [
    "DEFAULT_ADDRESS",
    "MatchingServicer",
    "serve",
    "to_context_response",
    "to_match_request",
    "to_match_response",
]

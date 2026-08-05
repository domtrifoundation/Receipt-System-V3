"""The `ProvingGroundsServicer` gRPC servicer (`proving_grounds.proto`) — wires
`test_runner.test_candidate()` to the wire surface, and keeps the real history
`GetTestHistory` reads from.

**`_history` is in-memory, not persisted** — the same honest, explicitly-scoped choice
`services/billing/service.py`'s own `SubscriptionService` makes for its own store; a
persistence adapter is real future work, not this pass's scope. Every `TestCandidate` call
this servicer actually ran is genuinely recorded here, in call order, for the lifetime of
this process.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

import threading

from .contracts import CandidateKind, TestCandidate, TestHistoryEntry
from .test_runner import BenchDispatcherRegistry, ContainerRunner, default_registry

DEFAULT_ADDRESS = "127.0.0.1:50090"

__all__ = ["DEFAULT_ADDRESS", "ProvingGroundsServicer", "serve"]


def _result_to_pb(pb, result):
    return pb.TestResultInfo(
        candidate_name=result.candidate.name, candidate_version=result.candidate.version,
        affected_api=result.candidate.affected_api, passed=result.passed,
        started_at=result.started_at.isoformat(), finished_at=result.finished_at.isoformat(),
        bench_summary=result.bench_summary, error_code=result.error_code, error_detail=result.error_detail,
    )


class ProvingGroundsServicer:
    """Implements `ProvingGroundsService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        *,
        dispatchers: BenchDispatcherRegistry | None = None,
        container_runner: ContainerRunner | None = None,
    ) -> None:
        self._dispatchers = dispatchers if dispatchers is not None else default_registry()
        self._container_runner = container_runner
        self._lock = threading.Lock()
        self._history: list[TestHistoryEntry] = []

    async def TestCandidate(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import proving_grounds_pb2 as pb
        from .test_runner import test_candidate

        try:
            kind = CandidateKind(request.kind)
        except ValueError:
            return pb.TestResultResponse(error_code="UNKNOWN_CANDIDATE_KIND", error_detail=f"unknown kind {request.kind!r}")

        candidate = TestCandidate(
            kind=kind, name=request.name, version=request.version, affected_api=request.affected_api,
            download_url=request.download_url, hf_token=request.hf_token, requested_by=request.requested_by,
        )
        kwargs = {"dispatchers": self._dispatchers}
        if self._container_runner is not None:
            kwargs["container_runner"] = self._container_runner
        result = await test_candidate(candidate, **kwargs)

        with self._lock:
            self._history.append(TestHistoryEntry(result=result))

        response = pb.TestResultResponse(error_code=result.error_code, error_detail=result.error_detail)
        response.result.CopyFrom(_result_to_pb(pb, result))
        return response

    async def GetTestHistory(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import proving_grounds_pb2 as pb

        with self._lock:
            entries = list(self._history)

        if request.affected_api:
            entries = [e for e in entries if e.result.candidate.affected_api == request.affected_api]
        limit = request.limit or 100
        entries = entries[-limit:]

        response = pb.TestHistoryResponse()
        for entry in entries:
            response.results.append(_result_to_pb(pb, entry.result))
        return response


async def serve(address: str = DEFAULT_ADDRESS, *, dispatchers: BenchDispatcherRegistry | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import proving_grounds_pb2_grpc

    server = grpc.aio.server()
    proving_grounds_pb2_grpc.add_ProvingGroundsServiceServicer_to_server(
        ProvingGroundsServicer(dispatchers=dispatchers), server
    )
    server.add_insecure_port(address)
    await server.start()
    return server

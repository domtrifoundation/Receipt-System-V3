"""The `ExecutionCoreService` gRPC servicer (§11) — thin by design.

Every real decision lives in `scheduler.py`, `pipeline.py`, `checkpointing.py`,
`retry_policy.py` and `state_machine.py`. This file translates protobuf messages to and from the
contract types and holds the run registry, and does nothing else. §1's boundary is what makes
that discipline load-bearing rather than tidy: V2's `daemon_loop` instantiated the menu system,
keyboard listener and dashboard inside the pipeline loop, and V3's process separation makes that
impossible only for as long as Interface's sole route into this API is this file.

**Concurrency bucket: async** (file 02's table), and this one is genuinely async rather than
async-by-classification. §10.1 is explicit that Execution Core is fundamentally an orchestrator
of other APIs' async gRPC calls — every stage it invokes is itself already async — so its own
hot path is await-all-the-way-down coordination with no blocking calls of its own to hide in a
thread. The scheduler's semaphores (§5.1) and the debounce coalescer (§5.2) are pure asyncio
primitives; this is `grpc.aio`, unlike `core/health/service.py` whose state is lock-guarded and
synchronous.

**Errors are data** (`docs/PRINCIPLES.md` §4.1): every response carries `error_code`/
`error_detail`; nothing raises across the boundary. A rejected transition, an unknown run id and
a run already shutting down are all honest `RunResponse` payloads.

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly as
`core/matching/service.py` and `core/health/service.py` both do, so this package stays importable
— and its tests meaningful — on an interpreter with no `grpcio` wheel.
"""

from __future__ import annotations

import asyncio

from .contracts import ExecutionConfig, ReceiptStage, Run, RunState, utcnow
from .metrics import ExecutionMetricsCollector
from .scheduler import RunCoalescer, RunScheduler
from .state_machine import ASSIGNABLE_STATES, transition

DEFAULT_ADDRESS = "127.0.0.1:50068"

#: How often `GetRunStatus` emits while a run is still in flight. A poll rather than a push
#: because the run's progress lives in a registry rather than a queue; the interval is short
#: enough that "live progress" is true and long enough that a webapp tab is not a busy loop.
PROGRESS_INTERVAL_SECONDS = 0.5


class RunRegistry:
    """The live run set, and the only mutable run state in this API.

    Exists because `Run` is frozen and `state_machine.transition` returns a new one: something
    has to hold the current object so that a `CancelRun` arriving mid-batch is visible to
    `pipeline.process_run`'s per-receipt check (§8). That is the whole reason this class is not
    just a dict — `is_cancelled_for` is the callable the pipeline closes over.
    """

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def put(self, run: Run) -> Run:
        self._runs[run.run_id] = run
        return run

    def list_all(self) -> tuple[Run, ...]:
        """Real, previously-missing enumeration — every run this process currently
        knows about, in memory (`RunRegistry` keeps no durable store yet, same known gap
        `CLAUDE.md` already documents). What the TUI's own Run Monitor screen needs to
        show anything at all; `GetRunStatus` alone requires already knowing a `run_id`."""
        return tuple(self._runs.values())

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def set_state(self, run_id: str, state: RunState) -> tuple[Run | None, str]:
        """Transition a registered run, returning `(run, error)` — errors as data (§4.1)."""
        run = self._runs.get(run_id)
        if run is None:
            return None, f"no run {run_id!r}"
        if state not in ASSIGNABLE_STATES:
            return run, f"{state.value!r} is not an assignable state (§3)"
        result = transition(run, state)
        if not result.applied:
            return run, result.error
        self._runs[run_id] = result.run
        return result.run, ""

    def is_cancelled_for(self, run_id: str):
        """A live cancellation signal for `pipeline.process_run` (§8).

        Returns a callable rather than a boolean on purpose: a boolean read once is the snapshot
        problem this registry exists to solve, and per-receipt checking of a value that cannot
        change is the decorative version of §8's fix.
        """

        def _check() -> bool:
            run = self._runs.get(run_id)
            return run is not None and run.state is RunState.SHUTTING_DOWN

        return _check


def _run_to_wire(run: Run, message):
    message.run_id = run.run_id
    message.user_id = run.user_id
    message.state = run.state.value
    message.opened_at = run.opened_at.isoformat()
    message.closing_started_at = (
        run.closing_started_at.isoformat() if run.closing_started_at else ""
    )
    message.receipt_count = run.receipt_count
    return message


class ExecutionCoreServicer:
    """§11's four RPCs. Translation only."""

    def __init__(
        self,
        *,
        config: ExecutionConfig | None = None,
        registry: RunRegistry | None = None,
        coalescer: RunCoalescer | None = None,
        scheduler: RunScheduler | None = None,
        metrics: ExecutionMetricsCollector | None = None,
        addresses: dict[str, str] | None = None,
    ) -> None:
        self._config = config or ExecutionConfig()
        self._registry = registry or RunRegistry()
        self._coalescer = coalescer or RunCoalescer(self._config.debounce)
        self._scheduler = scheduler or RunScheduler(
            self._config.concurrency.per_user_limit, self._config.concurrency.global_limit
        )
        self._metrics = metrics or ExecutionMetricsCollector()

        #: Real per-service addresses `SubmitReceipt`'s gateways connect to — resolved the
        #: same way every other cross-service lookup in this session works
        #: (`common/blob_client.resolve_service_address`), with each service's own
        #: hardcoded `DEFAULT_ADDRESS` as the dev-checkout fallback.
        self._addresses = addresses or {
            "preprocessing": "127.0.0.1:50072", "ocr": "127.0.0.1:50090",
            "persistence": "127.0.0.1:50076", "review_flagging": "127.0.0.1:50081",
        }

        from .gateways import InMemoryAttemptCounter, InMemoryCheckpointStore, GrpcReviewFlagger
        from .pipeline import Pipeline

        self._checkpoint_store = InMemoryCheckpointStore()
        self._pipeline = Pipeline(
            store=self._checkpoint_store,
            counter=InMemoryAttemptCounter(),
            flagger=GrpcReviewFlagger(self._addresses["review_flagging"]),
            config=self._config,
            metrics=self._metrics,
        )

    @property
    def registry(self) -> RunRegistry:
        return self._registry

    @property
    def coalescer(self) -> RunCoalescer:
        return self._coalescer

    @property
    def metrics(self) -> ExecutionMetricsCollector:
        return self._metrics

    async def StartRun(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import execution_core_pb2

        response = execution_core_pb2.RunResponse()
        user_id = request.user_id
        if not user_id:
            response.error_code = "invalid_request"
            response.error_detail = "user_id is required"
            return response

        outcome = self._coalescer.on_trigger(user_id, max(int(request.file_count or 1), 1))
        self._registry.put(outcome.run)
        _run_to_wire(outcome.run, response.run)
        response.started_new_run = outcome.started_new_run
        return response

    async def CancelRun(self, request, context=None):  # noqa: N802 - gRPC naming
        return self._transition_response(request.run_id, RunState.SHUTTING_DOWN)

    async def PauseRun(self, request, context=None):  # noqa: N802 - gRPC naming
        return self._transition_response(request.run_id, RunState.PAUSED)

    async def SubmitReceipt(self, request, context=None):  # noqa: N802 - gRPC naming
        """Real per-receipt processing (§11's own newly-added RPC — see `execution_core.
        proto`'s own comment for why StartRun alone was never enough). Runs under the
        real `RunScheduler` (`scheduler.acquire`) so concurrent receipts from different
        users genuinely run in parallel up to the configured per-user/global limits, and
        one busy user cannot starve everyone else — the identical concurrency model
        `RunScheduler`'s own docstring describes, now actually reached from a real RPC."""
        from .generated import execution_core_pb2 as pb
        from .receipt_orchestration import build_receipt_work
        from .gateways import GrpcOcrGateway, GrpcPersistenceGateway, GrpcPreprocessingGateway

        run = self._registry.get(request.run_id)
        if run is None:
            return pb.SubmitReceiptResponse(
                receipt_id=request.receipt_id, error_code="run_not_found",
                error_detail=f"no run {request.run_id!r} -- call StartRun first",
            )

        work = build_receipt_work(
            receipt_id=request.receipt_id, run_id=request.run_id, user_id=request.user_id,
            source_blob_ref=request.source_blob_ref, content_hash=request.content_hash,
            store=self._checkpoint_store,
            preprocessing=GrpcPreprocessingGateway(self._addresses["preprocessing"]),
            ocr=GrpcOcrGateway(self._addresses["ocr"]),
            persistence=GrpcPersistenceGateway(self._addresses["persistence"]),
            ocr_source=request.ocr_source or "preprocessed",
            ocr_engines=tuple(request.ocr_engines),
        )

        async with self._scheduler.acquire(request.user_id):
            outcome = await self._pipeline.process_receipt(run, work)

        response = pb.SubmitReceiptResponse(
            receipt_id=outcome.receipt_id,
            reached_stage=outcome.reached_stage.value if outcome.reached_stage else "",
            outcome=outcome.outcome.value,
        )
        if outcome.error:
            response.error_code = outcome.outcome.value
            response.error_detail = outcome.error
        elif outcome.written:
            written_checkpoint = await self._checkpoint_store.get_checkpoint(request.receipt_id, ReceiptStage.WRITTEN)
            if written_checkpoint is not None:
                response.persisted_receipt_id = written_checkpoint.stage_output_ref
        return response

    async def ListActiveRuns(self, request, context=None):  # noqa: N802 - gRPC naming
        """Real, previously-missing enumeration -- the actual gap behind the TUI's own
        Run Monitor screen never being buildable at all: `GetRunStatus` requires already
        knowing a `run_id`, and nothing exposed the set of runs this process knows
        about."""
        from .generated import execution_core_pb2 as pb

        response = pb.ListActiveRunsResponse()
        for run in self._registry.list_all():
            if request.user_id and run.user_id != request.user_id:
                continue
            _run_to_wire(run, response.runs.add())
        return response

    def _transition_response(self, run_id: str, state: RunState):
        from .generated import execution_core_pb2

        response = execution_core_pb2.RunResponse()
        run, error = self._registry.set_state(run_id, state)
        if run is None:
            response.error_code = "run_not_found"
            response.error_detail = error
            return response
        _run_to_wire(run, response.run)
        if error:
            response.error_code = "transition_rejected"
            response.error_detail = error
        return response

    async def GetRunStatus(self, request, context=None):  # noqa: N802 - gRPC naming
        """Server-streaming progress (§11).

        Streams until the run leaves its processing states, then emits one final frame. An
        unknown run id yields exactly one frame carrying the error rather than an empty stream —
        a stream that closes with nothing in it is indistinguishable from a network fault.
        """
        from .generated import execution_core_pb2

        run = self._registry.get(request.run_id)
        if run is None:
            frame = execution_core_pb2.RunProgress()
            frame.run_id = request.run_id
            frame.error_code = "run_not_found"
            frame.error_detail = f"no run {request.run_id!r}"
            yield frame
            return

        while True:
            current = self._registry.get(request.run_id)
            if current is None:
                return
            frame = execution_core_pb2.RunProgress()
            frame.run_id = current.run_id
            frame.state = current.state.value
            frame.receipts_total = current.receipt_count
            snapshot = self._metrics.snapshot()
            frame.receipts_completed = snapshot.runs_completed
            frame.current_stage_summary = f"run {current.state.value}"
            yield frame
            if current.state in (RunState.SHUTTING_DOWN, RunState.CLOSING):
                return
            await asyncio.sleep(PROGRESS_INTERVAL_SECONDS)


async def serve(address: str = DEFAULT_ADDRESS, *, config: ExecutionConfig | None = None, addresses: dict[str, str] | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import execution_core_pb2_grpc

    server = grpc.aio.server()
    execution_core_pb2_grpc.add_ExecutionCoreServiceServicer_to_server(
        ExecutionCoreServicer(config=config, addresses=addresses), server
    )
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


__all__ = [
    "DEFAULT_ADDRESS",
    "ExecutionCoreServicer",
    "PROGRESS_INTERVAL_SECONDS",
    "RunRegistry",
    "serve",
    "utcnow",
]


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        from pathlib import Path

        from common.blob_client import resolve_service_address
        from common.install_paths import resolve_install_root

        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        install_root = resolve_install_root(Path(__file__))
        fallbacks = {
            "preprocessing": "127.0.0.1:50072", "ocr": "127.0.0.1:50090",
            "persistence": "127.0.0.1:50076", "review_flagging": "127.0.0.1:50081",
        }
        resolved_addresses = fallbacks if install_root is None else {
            name: resolve_service_address(install_root, name, fallback) for name, fallback in fallbacks.items()
        }
        srv = await serve(addr, addresses=resolved_addresses)
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('execution_core')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())

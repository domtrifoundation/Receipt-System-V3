"""The `ReconciliationService` gRPC servicer (§6) — thin by design.

Every real decision lives in `checks/` and `propagation.py`. This file translates protobuf
messages to and from the contract types and nothing else, and here that discipline is load-
bearing rather than tidy: `docs/PRINCIPLES.md` §1.9's guarantee is a property of the functions
themselves — `checks.geo_vendor_cross_reference` reaching the identical Geo/Address function
Execution Core's `GEOD` stage calls, `propagation` reaching the identical Execution Core
checkpoint mechanism — not of this file. Any shortcut here that reimplemented a fragment of
either would break the property while every test of this surface kept passing.

**Concurrency bucket: async** (file 02's table), and §5 is precise about why it is not uniform.
Nine of the eleven checks are "fast, pure-Python logic over already-fetched data" — negligible
either way. §4.11's geo cross-reference is a genuine network call and is the reason this surface
is async at all. Bulk propagation is the one place this API has real CPU-bound work at scale, and
§5 routes it through Background Workers' `CPU_PROCESS` class rather than having this API build
its own parallel dispatch — so nothing in this file spawns a worker.

**Errors are data** (§4.1): every response carries `error_code`/`error_detail`. A receipt that
cannot be found, a check name that is not registered, and a propagation that hit conflicts are
all honest payloads.

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly as
`core/matching/service.py` does, so this package stays importable — and its tests meaningful —
on an interpreter with no `grpcio` wheel.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from .checks import CheckRegistry, default_registry
from .contracts import CheckOutcome, CheckResult, FlagEmitter, ReceiptSnapshot
from .metrics import ReconciliationMetricsCollector
from .propagation import propagate_correction

DEFAULT_ADDRESS = "127.0.0.1:50071"


class ReconciliationServicer:
    """§6's two RPCs. Translation only."""

    def __init__(
        self,
        *,
        registry: CheckRegistry | None = None,
        metrics: ReconciliationMetricsCollector | None = None,
        flag_emitter: FlagEmitter | None = None,
    ) -> None:
        self._registry = registry or default_registry()
        self._metrics = metrics or ReconciliationMetricsCollector()
        self._flag_emitter = flag_emitter

    @property
    def registry(self) -> CheckRegistry:
        return self._registry

    @property
    def metrics(self) -> ReconciliationMetricsCollector:
        return self._metrics

    async def run_checks(
        self,
        snapshot: ReceiptSnapshot,
        context: FrozenDict | None = None,
        check_names: tuple[str, ...] = (),
    ) -> tuple[CheckResult, ...]:
        """Run the inventory (or a named subset) and emit a flag for every hit.

        The in-process entry point, and the one `RunChecks` translates onto. Kept separate from
        the RPC method so Background Workers' own sweep over old receipts calls the identical
        function rather than going out and back through gRPC to reach it
        (`docs/PRINCIPLES.md` §1.9).

        A flag-emission failure does not discard the check results. The finding is real whether
        or not it reached the queue on the first attempt, and returning nothing would lose it
        entirely (§4.4).
        """
        ctx = context if context is not None else FrozenDict({})

        if check_names:
            results: list[CheckResult] = []
            for name in check_names:
                check = self._registry.get(name)
                if check is None:
                    results.append(
                        CheckResult(
                            check_name=name,
                            outcome=CheckOutcome.INCONCLUSIVE,
                            detail=f"no check named {name!r} is registered",
                        )
                    )
                    continue
                try:
                    results.append(await check.run(snapshot, ctx))
                except Exception as exc:  # noqa: BLE001 - one broken check, ten still reporting
                    results.append(
                        CheckResult(
                            check_name=name,
                            outcome=CheckOutcome.INCONCLUSIVE,
                            detail=f"check raised {type(exc).__name__}: {exc}",
                        )
                    )
            produced = tuple(results)
        else:
            produced = await self._registry.run_all(snapshot, ctx)

        for result in produced:
            self._metrics.record_check(result.check_name, result.outcome)
            if result.flagged and self._flag_emitter is not None:
                try:
                    await self._flag_emitter.create_flag(
                        snapshot.receipt_id, result.flag_type, result.evidence
                    )
                except Exception:  # noqa: BLE001 - see this method's docstring
                    pass

        return produced

    async def RunChecks(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import reconciliation_pb2

        response = reconciliation_pb2.RunChecksResponse()
        if not request.receipt_id:
            response.error_code = "invalid_request"
            response.error_detail = "receipt_id is required"
            return response

        results = await self.run_checks(
            ReceiptSnapshot(receipt_id=request.receipt_id),
            check_names=tuple(request.check_names),
        )
        for result in results:
            message = response.results.add()
            message.check_name = result.check_name
            message.flag_type = result.flag_type
            message.severity = result.severity.value
            message.outcome = result.outcome.value
            message.detail = result.detail
        return response

    async def PropagateCorrection(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import reconciliation_pb2

        response = reconciliation_pb2.PropagationJobResponse()
        response.error_code = "not_wired"
        response.error_detail = (
            "PropagateCorrection needs Persistence's writer and Execution Core's checkpoint "
            "store injected; propagation.propagate_correction is the working entry point"
        )
        return response


async def serve(address: str = DEFAULT_ADDRESS):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import reconciliation_pb2_grpc

    server = grpc.aio.server()
    reconciliation_pb2_grpc.add_ReconciliationServiceServicer_to_server(
        ReconciliationServicer(), server
    )
    server.add_insecure_port(address)
    await server.start()
    return server


__all__ = ["DEFAULT_ADDRESS", "ReconciliationServicer", "propagate_correction", "serve"]

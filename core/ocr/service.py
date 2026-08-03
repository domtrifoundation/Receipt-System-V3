"""The `OcrServicer` gRPC servicer (`ocr.proto`) — thin by design, matching
`core/preprocessing/service.py`'s own stated posture. Every real decision lives in
`engine_registry.py` and `corroboration.py`; this file translates protobuf messages to and
from those modules' own contract types and nothing else.

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly as
`core/preprocessing/service.py` does, so this package stays importable — and its tests
meaningful — on an interpreter with no `grpcio` wheel yet (`docs/MAINTENANCE.md` §8.1).
"""

from __future__ import annotations

from .contracts import BlobRef, BlobStoreGateway, EngineName, OcrRequest
from .engine_registry import OcrConfig, OcrEngineRegistry
from .metrics import OcrMetricsCollector

DEFAULT_ADDRESS = "127.0.0.1:50071"
PERSISTENCE_ADDRESS = "127.0.0.1:50076"


class OcrServicer:
    """Implements `OcrService`. Registered by name, so importing the generated stubs is
    `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        blob_store: BlobStoreGateway,
        *,
        config: OcrConfig | None = None,
    ) -> None:
        self._config = config or OcrConfig()
        self._metrics = OcrMetricsCollector()
        self._registry = OcrEngineRegistry(self._config, blob_store, self._metrics)

    async def Read(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import ocr_pb2 as pb

        ocr_request = OcrRequest(
            run_id=request.run_id,
            user_id=request.user_id,
            image_ref=BlobRef(logical_id=request.blob_ref),
            engines=frozenset(EngineName(e) for e in request.engines),
            timeout_ms=request.timeout_ms or 15_000,
        )
        result = await self._registry.run(ocr_request)

        response = pb.OcrReadResponse()
        response.merged_text = result.merged_text
        response.agreement = result.agreement.value
        response.confidence = result.confidence
        for reading in result.readings:
            msg = response.readings.add()
            msg.engine = reading.engine.value
            msg.text = reading.text
            msg.duration_ms = reading.duration_ms
            msg.device = reading.device
            if reading.error is not None:
                msg.error_code = reading.error.code.value
                msg.error_detail = reading.error.detail
            if reading.mean_confidence is not None:
                msg.has_mean_confidence = True
                msg.mean_confidence = reading.mean_confidence
            for region in reading.regions:
                region_msg = msg.regions.add()
                region_msg.text = region.text
                region_msg.confidence = region.confidence
                region_msg.box_x, region_msg.box_y, region_msg.box_w, region_msg.box_h = region.box
        return response

    async def ListEngines(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import ocr_pb2 as pb

        response = pb.ListEnginesResponse()
        response.available_engines.extend(
            sorted(e.value for e in await self._registry.available_engines())
        )
        response.enabled_engines.extend(
            sorted(e.value for e in await self._registry.enabled_engines())
        )
        return response


async def serve(
    address: str = DEFAULT_ADDRESS,
    *,
    blob_store: BlobStoreGateway,
    config: OcrConfig | None = None,
):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import ocr_pb2_grpc

    server = grpc.aio.server()
    ocr_pb2_grpc.add_OcrServiceServicer_to_server(
        OcrServicer(blob_store, config=config), server
    )
    server.add_insecure_port(address)
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main():
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        from common.blob_client import GrpcBlobStoreClient
        client = GrpcBlobStoreClient(PERSISTENCE_ADDRESS)
        srv = await serve(addr, blob_store=client)
        print(f"listening on {addr}", file=sys.stderr)
        await srv.wait_for_termination()

    asyncio.run(_main())

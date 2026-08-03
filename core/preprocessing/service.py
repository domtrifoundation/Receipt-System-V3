"""The `PreprocessingServicer` gRPC servicer (`preprocessing.proto`) — thin by design, matching
`core/geo_address/service.py`'s own stated posture. Every real decision lives in `raster.py`,
`generation.py`, and `variant_registry.py`; this file translates protobuf messages to and from
those modules' own contract types and nothing else.

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly as
`core/geo_address/service.py` does, so this package stays importable — and its tests
meaningful — on an interpreter with no `grpcio` wheel yet (`docs/MAINTENANCE.md` §8.1).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent import futures

from .contracts import BlobRef, BlobStoreGateway, RasterRequest, VariantKind, VariantRequest
from .generation import VariantExecutor
from .metrics import PreprocessingMetricsCollector
from .raster import rasterize
from .variant_registry import PreprocessingConfig, VariantRegistry

DEFAULT_ADDRESS = "127.0.0.1:50072"
PERSISTENCE_ADDRESS = "127.0.0.1:50076"


class PreprocessingServicer:
    """Implements `PreprocessingService`. Registered by name, so importing the generated stubs
    is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        blob_store_factory: Callable[[], BlobStoreGateway],
        *,
        config: PreprocessingConfig | None = None,
        worker_count: int | None = None,
    ) -> None:
        self._blob_store_factory = blob_store_factory
        self._config = config or PreprocessingConfig()
        self._executor = VariantExecutor(blob_store_factory, config=self._config, worker_count=worker_count)
        self._registry = VariantRegistry(self._config)
        #: Built and independently tested (`metrics.py`) but never actually instantiated
        #: anywhere in this servicer until caught — the same "declared, never wired"
        #: gap already found and fixed in every other API's own real assembly this
        #: session (Ingestion's `GoogleDriveSource`/`webhook_manager`, Inference's
        #: `max_concurrent_generations`, OCR's `per_engine_timeout_ms`).
        self._metrics = PreprocessingMetricsCollector()

    async def Rasterize(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import preprocessing_pb2 as pb

        raster_request = RasterRequest(
            run_id=request.run_id,
            user_id=request.user_id,
            source_ref=BlobRef(logical_id=request.source_blob_ref),
            page_index=request.page_index,
            scale=request.scale or 2.5,
        )
        result = await rasterize(raster_request, self._blob_store_factory())
        self._metrics.increment("rasters_failed" if result.error is not None else "rasters_succeeded")

        response = pb.RasterizeResponse()
        if result.image_ref is not None:
            response.image_blob_ref = result.image_ref.logical_id
        response.width = result.width
        response.height = result.height
        response.duration_ms = result.duration_ms
        response.device = result.device
        if result.error is not None:
            response.error_code = result.error.code.value
            response.error_detail = result.error.detail
        return response

    async def GenerateVariants(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import preprocessing_pb2 as pb

        kinds = frozenset(VariantKind(k) for k in request.kinds)
        variant_request = VariantRequest(
            run_id=request.run_id,
            user_id=request.user_id,
            image_ref=BlobRef(logical_id=request.image_blob_ref),
            kinds=kinds,
            device_preference=request.device_preference or "auto",
        )
        result = await self._executor.generate(variant_request)

        response = pb.GenerateVariantsResponse()
        for variant in result.variants:
            msg = response.variants.add()
            msg.kind = variant.kind.value
            if variant.image_ref is not None:
                msg.image_blob_ref = variant.image_ref.logical_id
            msg.duration_ms = variant.duration_ms
            msg.device = variant.device
            if variant.error is not None:
                msg.error_code = variant.error.code.value
                msg.error_detail = variant.error.detail
                self._metrics.increment("variants_failed")
            else:
                self._metrics.increment("variants_succeeded")
                self._metrics.increment(
                    "variants_run_on_opencl" if variant.device == "opencl" else "variants_run_on_cpu"
                )
        return response

    async def ListVariantKinds(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import preprocessing_pb2 as pb

        response = pb.ListVariantKindsResponse()
        response.available_kinds.extend(sorted(k.value for k in self._registry.available_kinds()))
        response.enabled_kinds.extend(sorted(k.value for k in self._registry.enabled_kinds()))
        return response


async def serve(
    address: str = DEFAULT_ADDRESS,
    *,
    blob_store_factory: Callable[[], BlobStoreGateway],
    config: PreprocessingConfig | None = None,
):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import preprocessing_pb2_grpc

    server = grpc.aio.server()
    preprocessing_pb2_grpc.add_PreprocessingServiceServicer_to_server(
        PreprocessingServicer(blob_store_factory, config=config), server
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
        srv = await serve(addr, blob_store_factory=lambda: client)
        print(f"listening on {addr}", file=sys.stderr)
        await srv.wait_for_termination()

    asyncio.run(_main())

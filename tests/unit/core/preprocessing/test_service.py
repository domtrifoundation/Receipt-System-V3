"""The `PreprocessingServicer` gRPC surface (`preprocessing.proto`).

`nox -s forward_compat` deliberately installs a narrow dependency set that excludes grpcio,
because grpcio has no prebuilt wheel for 3.15 yet (`docs/MAINTENANCE.md` §8.1). A bare
module-level `import grpc` here would break *collection* under that session on 3.15, not just
skip these tests — the same guard `core/auth/`'s and `core/account_guardian/`'s own servicer
tests already carry.

Constructing a `PreprocessingServicer` builds a real `ProcessPoolExecutor` (via its own
`VariantExecutor`), so every test here is genuinely real infrastructure, not a lightweight unit
test — all marked `slow`, matching this suite's own convention elsewhere in the repo.

The blob-store factory is module-level, not a closure, for the same reason
`test_generation.py`'s own version is: it has to survive being pickled to a real worker process
under Windows's `spawn` start method.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.preprocessing.contracts import BlobRef  # noqa: E402
from core.preprocessing.service import PreprocessingServicer, serve  # noqa: E402

from .conftest import encode_png_bytes, make_checkerboard, make_synthetic_pdf  # noqa: E402


@dataclass(frozen=True)
class _FileBlobStore:
    directory: str

    async def read_blob(self, ref: BlobRef) -> bytes:
        return (Path(self.directory) / ref.logical_id).read_bytes()

    async def write_blob(self, data: bytes) -> BlobRef:
        logical_id = f"{uuid.uuid4()}.bin"
        (Path(self.directory) / logical_id).write_bytes(data)
        return BlobRef(logical_id=logical_id)


def _make_test_blob_store() -> _FileBlobStore:
    return _FileBlobStore(directory=os.environ["PREPROCESSING_SERVICE_TEST_BLOB_DIR"])


@pytest.fixture
def blob_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPROCESSING_SERVICE_TEST_BLOB_DIR", str(tmp_path))
    yield tmp_path


@pytest.mark.slow
def test_rasterize_through_the_servicer_directly(blob_dir):
    async def go():
        store = _make_test_blob_store()
        source_ref = await store.write_blob(make_synthetic_pdf())
        servicer = PreprocessingServicer(_make_test_blob_store)
        try:
            from core.preprocessing.generated import preprocessing_pb2 as pb

            request = pb.RasterizeRequest(
                run_id="r1", user_id="u1", source_blob_ref=source_ref.logical_id,
                page_index=0, scale=2.0,
            )
            return await servicer.Rasterize(request)
        finally:
            servicer._executor.shutdown()

    response = asyncio.run(go())
    assert response.error_code == ""
    assert response.width > 0 and response.height > 0


@pytest.mark.slow
def test_servicer_metrics_actually_increment_not_just_declared(blob_dir):
    """The concrete fix for a real gap: `PreprocessingMetricsCollector` was built and
    independently tested (`test_metrics.py`) but never instantiated anywhere in
    `PreprocessingServicer` at all — every rasterize/generate call went uncounted."""

    async def go():
        store = _make_test_blob_store()
        source_ref = await store.write_blob(make_synthetic_pdf())
        servicer = PreprocessingServicer(_make_test_blob_store)
        try:
            from core.preprocessing.generated import preprocessing_pb2 as pb

            request = pb.RasterizeRequest(
                run_id="r1", user_id="u1", source_blob_ref=source_ref.logical_id,
                page_index=0, scale=2.0,
            )
            await servicer.Rasterize(request)
            return servicer._metrics.snapshot()
        finally:
            servicer._executor.shutdown()

    snapshot = asyncio.run(go())
    assert snapshot.rasters_succeeded == 1
    assert snapshot.rasters_failed == 0


@pytest.mark.slow
def test_list_variant_kinds_reflects_the_real_registry(blob_dir):
    async def go():
        servicer = PreprocessingServicer(_make_test_blob_store)
        try:
            from core.preprocessing.generated import preprocessing_pb2 as pb

            return await servicer.ListVariantKinds(pb.ListVariantKindsRequest())
        finally:
            servicer._executor.shutdown()

    response = asyncio.run(go())
    assert "standard" in response.available_kinds
    assert "denoise" in response.available_kinds
    assert set(response.enabled_kinds) == {"standard", "bw_threshold"}


@pytest.mark.slow
def test_a_real_client_can_rasterize_and_generate_variants_over_an_actual_grpc_connection(blob_dir):
    """No stub of the thing under test: a real `grpc.aio` server on a real loopback socket, a
    real client stub, real `ProcessPoolExecutor` workers underneath — the same end-to-end
    discipline `services/setup/`'s own real-connection test already established for this repo.
    """
    from core.preprocessing.generated import preprocessing_pb2, preprocessing_pb2_grpc

    async def go():
        address = "127.0.0.1:19710"
        server = await serve(address, blob_store_factory=_make_test_blob_store)
        try:
            channel = grpc.aio.insecure_channel(address)
            stub = preprocessing_pb2_grpc.PreprocessingServiceStub(channel)

            store = _make_test_blob_store()
            source_ref = await store.write_blob(encode_png_bytes(make_checkerboard(size=64)))

            rasterize_response = await stub.Rasterize(
                preprocessing_pb2.RasterizeRequest(
                    run_id="r1", user_id="u1", source_blob_ref=source_ref.logical_id,
                    page_index=0, scale=1.0,
                )
            )
            assert rasterize_response.error_code == ""

            variants_response = await stub.GenerateVariants(
                preprocessing_pb2.GenerateVariantsRequest(
                    run_id="r1", user_id="u1", image_blob_ref=rasterize_response.image_blob_ref,
                    kinds=["standard", "bw_threshold", "deskew"], device_preference="cpu",
                )
            )
            await channel.close()
            return variants_response
        finally:
            await server.stop(None)

    response = asyncio.run(go())
    kinds_seen = {v.kind for v in response.variants}
    assert kinds_seen == {"standard", "bw_threshold", "deskew"}
    for variant in response.variants:
        assert variant.error_code == "", variant.error_detail
        assert variant.image_blob_ref

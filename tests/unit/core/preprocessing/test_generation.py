"""`VariantExecutor` (`v3-deepdive-03-preprocessing-api.md` §8) — real `ProcessPoolExecutor`
workers, not a thread-pool stand-in for them.

**Every helper a worker needs to reach is defined at module level, deliberately, not nested
inside a test function.** Confirmed directly during development: a closure genuinely cannot be
pickled (`pickle.dumps` raises `PicklingError: Can't pickle local object`), and Windows's
`spawn` start method needs every object crossing the process boundary to be importable by
reference. A test written with a locally-defined fake blob store would pass on a platform using
`fork` and fail — or worse, silently hang — on Windows, which is exactly the kind of
platform-dependent test bug this suite is built to avoid.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from core.preprocessing.contracts import BlobRef, VariantKind, VariantRequest
from core.preprocessing.generation import VariantExecutor
from core.preprocessing.variant_registry import PreprocessingConfig

from .conftest import make_checkerboard, encode_png_bytes


@dataclass(frozen=True)
class _FileBlobStore:
    """A real, picklable, file-backed `BlobStoreGateway` — a frozen dataclass holding only a
    directory path (a plain string) survives being pickled and sent to a worker process, and
    real file I/O is genuinely shared across separate processes the way in-memory state is not.
    """

    directory: str

    async def read_blob(self, ref: BlobRef) -> bytes:
        return (Path(self.directory) / ref.logical_id).read_bytes()

    async def write_blob(self, data: bytes) -> BlobRef:
        logical_id = f"{uuid.uuid4()}.bin"
        (Path(self.directory) / logical_id).write_bytes(data)
        return BlobRef(logical_id=logical_id)


def _make_test_blob_store() -> _FileBlobStore:
    """The picklable, zero-argument factory `VariantExecutor` requires — a plain module-level
    function, not a closure over a test's own local directory (a real path is resolved via the
    environment variable below instead, since the factory itself cannot close over anything).
    """
    import os

    directory = os.environ["PREPROCESSING_TEST_BLOB_DIR"]
    return _FileBlobStore(directory=directory)


@pytest.fixture
def blob_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPROCESSING_TEST_BLOB_DIR", str(tmp_path))
    yield tmp_path


@pytest.mark.slow
def test_variant_executor_runs_real_worker_processes_end_to_end(blob_dir):
    store = _make_test_blob_store()
    import asyncio

    async def go():
        source_ref = await store.write_blob(encode_png_bytes(make_checkerboard(size=64)))
        executor = VariantExecutor(_make_test_blob_store, worker_count=2)
        try:
            request = VariantRequest(
                run_id="r1", user_id="u1", image_ref=source_ref,
                kinds=frozenset({VariantKind.STANDARD, VariantKind.BW_THRESHOLD, VariantKind.DESKEW}),
                device_preference="cpu",
            )
            return await executor.generate(request)
        finally:
            executor.shutdown()

    result = asyncio.run(go())

    assert len(result.variants) == 3
    for variant in result.variants:
        assert variant.error is None, variant.error
        assert variant.image_ref is not None
        assert (blob_dir / variant.image_ref.logical_id).exists()


@pytest.mark.slow
def test_variant_executor_reports_every_requested_kind_even_on_failure(blob_dir):
    """Never silently drops a requested kind (§3's own stated convention) — a source that does
    not exist at all must still produce one `Variant` per requested kind, each with its own
    error, not a hang or a truncated result list."""
    import asyncio

    async def go():
        bad_ref = BlobRef(logical_id="this-does-not-exist.bin")
        executor = VariantExecutor(_make_test_blob_store, worker_count=1)
        try:
            request = VariantRequest(
                run_id="r1", user_id="u1", image_ref=bad_ref,
                kinds=frozenset({VariantKind.STANDARD, VariantKind.BW_THRESHOLD}),
                device_preference="cpu",
            )
            return await executor.generate(request)
        finally:
            executor.shutdown()

    result = asyncio.run(go())

    assert len(result.variants) == 2
    for variant in result.variants:
        assert variant.error is not None
        assert variant.image_ref is None


@pytest.mark.slow
def test_variant_executor_respects_config_across_the_process_boundary(blob_dir):
    """The whole reason config crosses the boundary as plain data rather than a live registry
    object: a worker must apply the *caller's* configuration, not some default baked into the
    worker process at spawn time."""
    import asyncio
    import numpy as np

    async def go():
        source_ref = await _make_test_blob_store().write_blob(
            encode_png_bytes(np.full((32, 32, 3), 100, dtype=np.uint8))
        )
        config = PreprocessingConfig(
            variants_enabled=frozenset({VariantKind.LOW_CONTRAST}), low_contrast_alpha=0.2
        )
        executor = VariantExecutor(_make_test_blob_store, config=config, worker_count=1)
        try:
            request = VariantRequest(
                run_id="r1", user_id="u1", image_ref=source_ref,
                kinds=frozenset({VariantKind.LOW_CONTRAST}), device_preference="cpu",
            )
            return await executor.generate(request), source_ref

        finally:
            executor.shutdown()

    result, source_ref = asyncio.run(go())
    assert result.variants[0].error is None

    import cv2

    output_bytes = (blob_dir / result.variants[0].image_ref.logical_id).read_bytes()
    output_img = cv2.imdecode(np.frombuffer(output_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    # alpha=0.2 on a constant-100 image should land near 100*0.2=20, not the default alpha=0.6's
    # own ~60 — proving the configured value, not a hardcoded default, actually ran.
    assert output_img.mean() < 30

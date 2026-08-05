"""`VariantExecutor` — `ProcessPoolExecutor` dispatch for variant generation (deep-dive §8).

**Why multiprocessing, not threading, precisely** (§8.1-8.2): producing one variant is a short
*chain* of several OpenCV calls with real Python-level orchestration between them — more
opportunity for GIL-holding overhead to eat into parallelism than OCR API's single big blocking
call per engine has. Separately, and independently sufficient on its own: `opencv-python` does
not currently build at all under Python's free-threaded (`3.14t`) build (`opencv/opencv#27933`,
tracked by Telemetrees) — free-threading is not a currently-usable alternative here, on top of
the threading-shape argument.

**§8.4's real pitfall, and why this module is shaped the way it is**: `ProcessPoolExecutor`
pickles function arguments by default, and a closure (a `variant_registry.py`-built generator
like `low_contrast_factory(alpha=0.6)`'s own returned function) genuinely cannot be pickled at
all — confirmed directly (`pickle.dumps` raises `PicklingError: Can't pickle local object`) —
which rules out passing a `VariantRegistry`'s generators to a worker directly, on top of §8.4's
own stated reason to avoid pickling image *bytes*. The fix for both: only plain, picklable data
crosses the process boundary — a `VariantKind`, a `PreprocessingConfig`, a `BlobRef` — and each
worker process reconstructs its own tiny `VariantRegistry` from that config and re-fetches the
image itself via the blob store, rather than receiving a live registry or decoded pixels from
the parent.

**The blob-store client inside a worker is a second, separate instance of this same
constraint.** A real `BlobStoreGateway` implementation (whatever concretely backs it — most
likely a gRPC client to Persistence) generally cannot cross a process boundary either, for the
same reason a closure cannot: live connection state (sockets, channels) does not pickle.
`blob_store_factory` is therefore also required to be a plain, picklable, zero-argument
callable — a module-level function or a simple frozen-dataclass-with-`__call__`, never a
closure — that each worker calls exactly once to construct its *own* connection, the same
lazy-per-process-construction pattern a database connection pool uses across a process pool.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from .contracts import BlobRef, BlobStoreGateway, Variant, VariantKind, VariantRequest, VariantResult
from .errors import PreprocessingError, PreprocessingErrorCode, VariantGenerationFailed
from .hardware import resolve_device, to_processing_array
from .raster import decode_image_bytes, encode_image_png, sniff_format
from .variant_registry import PreprocessingConfig, VariantRegistry

__all__ = ["VariantExecutor"]

#: What a worker actually needs to reconstruct everything itself, in one picklable bundle
#: rather than several loose positional arguments — plain data only (`docs/PRINCIPLES.md`
#: §2.1's own frozen-dataclass discipline, applied here for the same reason it always is:
#: nothing on this type can mutate out from under a worker that received a copy of it).
@dataclass(frozen=True)
class _WorkerJob:
    image_ref: BlobRef
    kind: VariantKind
    device_preference: str
    config: PreprocessingConfig
    blob_store_factory: Callable[[], BlobStoreGateway]


def _run_one_variant(job: _WorkerJob) -> Variant:
    """The `ProcessPoolExecutor` worker function itself — module-level, not a closure, so it
    is picklable and importable-by-reference the way Windows's `spawn` start method requires.

    Never raises across the executor boundary: a genuine failure (a malformed image, a variant
    generator hitting a real OpenCV error on this specific image) comes back as a `Variant`
    with `image_ref=None` and `.error` set, matching every other API's identical
    errors-are-data convention (`docs/PRINCIPLES.md` §4.1).
    """
    blob_store = job.blob_store_factory()
    registry = VariantRegistry(job.config)

    async def _do_it() -> Variant:
        source_bytes = await blob_store.read_blob(job.image_ref)
        image = decode_image_bytes(source_bytes, page_index=0, scale=1.0)
        device = resolve_device(job.device_preference)
        processing_image = to_processing_array(image, device)

        generator = registry.get(job.kind)
        try:
            result_image = generator(processing_image)
        except Exception as exc:  # noqa: BLE001 - converted to this package's own error taxonomy
            raise VariantGenerationFailed(f"{job.kind.value} failed: {exc}") from exc

        if hasattr(result_image, "get"):  # cv2.UMat -> plain array before re-encoding to PNG
            result_image = result_image.get()
        encoded = encode_image_png(result_image)
        output_ref = await blob_store.write_blob(encoded)
        return Variant(kind=job.kind, image_ref=output_ref, duration_ms=0, device=device)

    try:
        return asyncio.run(_do_it())
    except VariantGenerationFailed as exc:
        return Variant(
            kind=job.kind, image_ref=None, duration_ms=0, device="cpu",
            error=PreprocessingError(code=PreprocessingErrorCode.VARIANT_GENERATION_FAILED, detail=str(exc)),
        )
    except Exception as exc:  # noqa: BLE001 - a source-read/decode failure, not a generator failure
        return Variant(
            kind=job.kind, image_ref=None, duration_ms=0, device="cpu",
            error=PreprocessingError(code=PreprocessingErrorCode.VARIANT_GENERATION_FAILED, detail=str(exc)),
        )


class VariantExecutor:
    def __init__(
        self,
        blob_store_factory: Callable[[], BlobStoreGateway],
        *,
        config: PreprocessingConfig | None = None,
        worker_count: int | None = None,
        max_concurrent_opencl_jobs: int = 2,
    ) -> None:
        """`worker_count=None` lets `ProcessPoolExecutor` pick its own default (CPU count) —
        §7's own `worker_pool_size: 0` config meaning "auto-detect from Setup API's hardware
        profile" is a future refinement once that profile is actually wired through here, not
        invented as a guess in this constructor.

        `max_concurrent_opencl_jobs`, a real, live-found correction to this package's own
        `CLAUDE.md` gotcha ("UMat's OpenCL buffers are small and short-lived per-image... a
        per-image reserve/release round trip to Health API would be real, disproportionate
        overhead") — that reasoning assumed one receipt's worth of OpenCL usage at a time.
        Under real concurrent-receipt load (`docs/PRINCIPLES.md`-driven live pipeline testing,
        not a synthetic benchmark) every `"auto"`-resolved variant job across every in-flight
        receipt independently opens its own OpenCL context against the same physical GPU in
        its own `ProcessPoolExecutor` worker process, with nothing bounding how many run at
        once — confirmed live: 5 concurrent receipts x up to 5 variants each drove the real
        installed OpenCL driver to `CL_OUT_OF_RESOURCES`, which OpenCV's C++ layer reports via
        `std::terminate()` — **uncatchable from Python**, killing the worker process outright,
        not a `cv2.error` this module's own existing `except Exception` in `_run_one_variant`
        could ever catch. A full Health-API-shaped reservation ledger (§6.7's own heavier
        mechanism, deliberately not built for this package) is more machinery than this needs;
        a plain `asyncio.Semaphore` gating only the jobs `resolve_device` actually resolves to
        `"opencl"` is enough to keep real concurrent GPU contexts bounded, while `"cpu"`-
        resolved jobs stay fully unbounded across the real worker pool. `2`, a conservative,
        reasoned starting point (this project's own `estimated_vram_mb` fields elsewhere carry
        the identical "reasoned placeholder, not bench-measured" caveat), not the literal
        highest concurrency this GPU can sustain — refine from real measurement once a bench
        exists, the same posture as those VRAM estimates."""
        self._blob_store_factory = blob_store_factory
        self._config = config or PreprocessingConfig()
        self._pool = ProcessPoolExecutor(max_workers=worker_count)
        self._opencl_gate = asyncio.Semaphore(max(1, max_concurrent_opencl_jobs))

    async def _dispatch(self, loop: asyncio.AbstractEventLoop, job: _WorkerJob) -> Variant:
        if resolve_device(job.device_preference) == "opencl":
            async with self._opencl_gate:
                return await loop.run_in_executor(self._pool, _run_one_variant, job)
        return await loop.run_in_executor(self._pool, _run_one_variant, job)

    async def generate(self, request: VariantRequest) -> VariantResult:
        loop = asyncio.get_running_loop()
        jobs = [
            _WorkerJob(
                image_ref=request.image_ref,
                kind=kind,
                device_preference=request.device_preference,
                config=self._config,
                blob_store_factory=self._blob_store_factory,
            )
            for kind in request.kinds
        ]
        variants = await asyncio.gather(*(self._dispatch(loop, job) for job in jobs))
        return VariantResult(variants=tuple(variants))

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)

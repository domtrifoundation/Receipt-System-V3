"""`PresetWorker` — a handle to a persistent **child process**, not a thread (deep-dive
§6.1, correcting an earlier thread-pool sketch — `core/execution_core/CLAUDE.md`'s own
correction pattern applied here). The real `og.Model`/`og.Generator` objects
(`backends/onnx_genai_backend.py`) live entirely inside that child process; Inference
API's own service process never imports `onnxruntime_genai`'s native bindings at all.

**Why a real process, not `run_in_executor`:** a segfault or driver crash inside
`onnxruntime-genai`'s own native code must stay contained to the one preset's worker,
never take down this service's own process (and every other loaded preset with it) — the
identical reasoning behind `core/preprocessing/generation.py`'s own `ProcessPoolExecutor`
choice, applied here because generation is the more expensive, more crash-prone native call
of the two.

**Everything that crosses `request_queue`/`response_queue` is plain, picklable data** —
`_WorkerJob`/`_WorkerResponse` are module-level frozen dataclasses, never closures, for the
same reason Preprocessing's own worker jobs are: Windows's `spawn` start method needs every
object crossing the process boundary to be importable by reference, and a closure cannot
be pickled at all (`PicklingError: Can't pickle local object`, confirmed directly during
Preprocessing API's own development this session).

Confirmed live *this session*, without needing real model weights: the actual
`multiprocessing.Process`/`Queue` mechanics — worker startup, the load-status handshake,
the micro-batch drain loop, per-request response routing via a single dedicated reader
task (never N racing consumers on one shared queue), and process-death detection failing
every pending caller with `WorkerUnavailable` rather than hanging forever
(`tests/unit/core/inference/test_generation.py`). What is *not* verified this session is
`backends/onnx_genai_backend.py`'s own real generation call — see that module's own
docstring.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import queue as queue_module
import time
from dataclasses import dataclass
from typing import Callable

from .batching import drain_batch
from .contracts import GenerationRequest, GenerationResult, InferenceError, InferenceErrorCode
from .errors import GenerationCrashed, GenerationTimeout, ModelLoadFailed, WorkerUnavailable
from .structured_output import salvage_partial_json
from .tool_calling import parse_tool_call

__all__ = ["PresetWorker", "TruncationConfig"]

_SHUTDOWN_SENTINEL = "__shutdown__"


@dataclass(frozen=True)
class TruncationConfig:
    """Deep-dive §5.2's own retry policy, as real config rather than a hardcoded constant."""

    retry_multiplier: float = 2.0


@dataclass(frozen=True)
class _WorkerJob:
    request_id: str
    request: GenerationRequest
    grammar_schema: dict | None
    images: tuple[bytes, ...] = ()


@dataclass(frozen=True)
class _WorkerResponse:
    request_id: str
    result: GenerationResult


@dataclass(frozen=True)
class _LoadStatus:
    ok: bool
    detail: str = ""


class _WorkerDied(Exception):
    pass


def _default_backend_factory():
    from .backends.onnx_genai_backend import OnnxGenAiBackend

    return OnnxGenAiBackend()


def _generate_with_retry(
    backend, prompt: str, grammar_schema: dict | None, max_tokens: int, temperature: float,
    truncation: TruncationConfig, images: tuple[bytes, ...] = (),
    reasoning_marker: str | None = None, reasoning_token_budget: int = 0,
) -> tuple:
    """Deep-dive §5.2: on `LENGTH`, retry once with a larger budget before giving up; if
    the retry also truncates, fall back to a salvage parse of the partial output rather
    than hard-failing. Returns `(BackendGenerationOutput, retried: bool)`."""
    from .contracts import FinishReason

    output = backend.generate(
        prompt, grammar_schema=grammar_schema, max_tokens=max_tokens, temperature=temperature,
        images=images, reasoning_marker=reasoning_marker, reasoning_token_budget=reasoning_token_budget,
    )
    if output.finish_reason != FinishReason.LENGTH:
        return (output, False)

    retried_budget = int(max_tokens * truncation.retry_multiplier)
    retried_output = backend.generate(
        prompt, grammar_schema=grammar_schema, max_tokens=retried_budget, temperature=temperature,
        images=images, reasoning_marker=reasoning_marker, reasoning_token_budget=reasoning_token_budget,
    )
    if retried_output.finish_reason != FinishReason.LENGTH or grammar_schema is None:
        return (retried_output, True)

    salvaged = salvage_partial_json(retried_output.text)
    if salvaged is not None:
        import json

        salvaged_output = type(retried_output)(
            text=json.dumps(salvaged), finish_reason=FinishReason.LENGTH,
            schema_valid=False, tool_call_json=retried_output.tool_call_json,
        )
        return (salvaged_output, True)
    return (retried_output, True)


def _build_result(request: GenerationRequest, output, device: str, duration_ms: int) -> GenerationResult:
    from .contracts import FinishReason

    tool_call = None
    finish_reason = output.finish_reason
    if request.tools:
        parsed = parse_tool_call(output.text)
        if parsed is not None:
            from common.frozen_dict import FrozenDict

            name, arguments = parsed
            from .contracts import ToolCall

            tool_call = ToolCall(name=name, arguments=FrozenDict(arguments))
            finish_reason = FinishReason.TOOL_CALL if finish_reason == FinishReason.STOP else finish_reason

    return GenerationResult(
        text="" if tool_call is not None else output.text,
        tool_call=tool_call,
        finish_reason=finish_reason,
        schema_valid=output.schema_valid,
        device=device,
        duration_ms=duration_ms,
    )


def _worker_main(
    model_dir: str,
    device: str,
    request_queue: multiprocessing.Queue,
    response_queue: multiprocessing.Queue,
    control_queue: multiprocessing.Queue,
    batch_window_ms: int,
    truncation: TruncationConfig,
    backend_factory: Callable[[], object] = _default_backend_factory,
    reasoning_marker: str | None = None,
    reasoning_token_budget: int = 0,
) -> None:
    """Runs entirely inside the child process. Module-level, not a closure — see the
    module docstring's own pickling note (this is the `multiprocessing.Process` target,
    which must be importable by reference under `spawn`).

    `backend_factory` defaults to the real `OnnxGenAiBackend`, mirroring
    `core/preprocessing/generation.py`'s own `blob_store_factory` seam — a plain,
    picklable, zero-argument callable is what lets `tests/unit/core/inference/
    test_generation.py` exercise this module's *real* multiprocessing/queue/batching/
    crash-isolation mechanics against a lightweight fake backend, without needing real
    model weights to validate the concurrency design itself."""
    from .backends.onnx_genai_backend import build_prompt

    backend = backend_factory()
    try:
        backend.load(model_dir, device)
    except ModelLoadFailed as exc:
        control_queue.put(_LoadStatus(ok=False, detail=str(exc)))
        return
    control_queue.put(_LoadStatus(ok=True))

    while True:
        batch = drain_batch(request_queue, window_ms=batch_window_ms, max_batch_size=16)
        for item in batch:
            if item == _SHUTDOWN_SENTINEL:
                backend.unload()
                return
            job: _WorkerJob = item
            start = time.monotonic()
            try:
                prompt = build_prompt(job.request.messages)
                output, _retried = _generate_with_retry(
                    backend, prompt, job.grammar_schema, job.request.max_tokens,
                    job.request.temperature, truncation, job.images,
                    reasoning_marker, reasoning_token_budget,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                result = _build_result(job.request, output, device, duration_ms)
            except GenerationCrashed as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                result = GenerationResult.failure(
                    InferenceError(InferenceErrorCode.GENERATION_CRASHED, str(exc)),
                    duration_ms, device,
                )
            except Exception as exc:  # noqa: BLE001 - an unanticipated crash still stays contained
                duration_ms = int((time.monotonic() - start) * 1000)
                result = GenerationResult.failure(
                    InferenceError(InferenceErrorCode.GENERATION_CRASHED, f"{type(exc).__name__}: {exc}"),
                    duration_ms, device,
                )
            response_queue.put(_WorkerResponse(job.request_id, result))


class PresetWorker:
    """A handle to a persistent child process — see the module docstring."""

    def __init__(
        self,
        preset_name: str,
        model_dir: str,
        device: str,
        *,
        batch_window_ms: int = 30,
        truncation: TruncationConfig | None = None,
        load_timeout_seconds: float = 60.0,
        backend_factory: Callable[[], object] = _default_backend_factory,
        reasoning_marker: str | None = None,
        reasoning_token_budget: int = 0,
        max_concurrent_generations: int = 4,
    ) -> None:
        self._preset_name = preset_name
        self._model_dir = model_dir
        self._device = device
        self._batch_window_ms = batch_window_ms
        self._truncation = truncation or TruncationConfig()
        self._load_timeout_seconds = load_timeout_seconds
        self._backend_factory = backend_factory
        self._reasoning_marker = reasoning_marker
        self._reasoning_token_budget = reasoning_token_budget
        #: Deep-dive §10's own named config value ("queue depth cap before backpressure,
        #: per preset") — a real `asyncio.Semaphore`, acquired in `submit()` around the
        #: dispatch-and-await-response span so the (N+1)th concurrent caller genuinely
        #: waits rather than piling unboundedly many requests into this worker's own
        #: request queue. Created lazily in `load()`, not here, since it must be bound to
        #: the event loop `load()` actually runs on.
        self._max_concurrent_generations = max_concurrent_generations
        self._generation_semaphore: asyncio.Semaphore | None = None

        self._process: multiprocessing.Process | None = None
        self._request_queue: multiprocessing.Queue | None = None
        self._response_queue: multiprocessing.Queue | None = None
        self._control_queue: multiprocessing.Queue | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._next_id = 0

    async def load(self) -> None:
        self._generation_semaphore = asyncio.Semaphore(self._max_concurrent_generations)
        self._request_queue = multiprocessing.Queue()
        self._response_queue = multiprocessing.Queue()
        self._control_queue = multiprocessing.Queue()
        self._process = multiprocessing.Process(
            target=_worker_main,
            args=(
                self._model_dir, self._device, self._request_queue, self._response_queue,
                self._control_queue, self._batch_window_ms, self._truncation,
                self._backend_factory, self._reasoning_marker, self._reasoning_token_budget,
            ),
            daemon=True,
        )
        self._process.start()

        loop = asyncio.get_running_loop()
        try:
            status: _LoadStatus = await asyncio.wait_for(
                loop.run_in_executor(None, self._control_queue.get),
                timeout=self._load_timeout_seconds,
            )
        except TimeoutError as exc:
            self._process.terminate()
            raise ModelLoadFailed(f"worker did not report load status within {self._load_timeout_seconds}s") from exc
        if not status.ok:
            raise ModelLoadFailed(status.detail)

        self._reader_task = asyncio.ensure_future(self._reader_loop())

    def _get_response_with_poll(self):
        while True:
            try:
                return self._response_queue.get(timeout=0.5)
            except queue_module.Empty:
                if self._process is None or not self._process.is_alive():
                    raise _WorkerDied() from None

    async def _reader_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                response: _WorkerResponse = await loop.run_in_executor(
                    None, self._get_response_with_poll
                )
            except _WorkerDied:
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(WorkerUnavailable("worker process died"))
                self._pending.clear()
                return
            future = self._pending.pop(response.request_id, None)
            if future is not None and not future.done():
                future.set_result(response.result)

    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    async def submit(
        self, request: GenerationRequest, grammar_schema: dict | None, images: tuple[bytes, ...] = ()
    ) -> GenerationResult:
        if not self.is_alive():
            raise WorkerUnavailable(f"preset {self._preset_name!r} worker is not running")

        # Deep-dive §10's own backpressure cap: the (N+1)th concurrent caller genuinely
        # waits here for a free slot rather than piling an unbounded number of requests
        # into this worker's own queue — the wait itself is not charged against
        # `request.timeout_ms`, which budgets the generation call itself, not queueing.
        # `_generation_semaphore` is always set by this point — `is_alive()` above only
        # returns `True` once `load()` has run, and `load()` is what creates it.
        async with self._generation_semaphore:
            self._next_id += 1
            request_id = f"{self._preset_name}-{self._next_id}"
            loop = asyncio.get_running_loop()
            future: asyncio.Future = loop.create_future()
            self._pending[request_id] = future

            job = _WorkerJob(request_id, request, grammar_schema, images)
            await loop.run_in_executor(None, self._request_queue.put, job)
            try:
                return await asyncio.wait_for(future, timeout=request.timeout_ms / 1000)
            except TimeoutError as exc:
                self._pending.pop(request_id, None)
                raise GenerationTimeout(f"exceeded {request.timeout_ms}ms") from exc

    async def shutdown(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._request_queue is not None and self.is_alive():
            self._request_queue.put(_SHUTDOWN_SENTINEL)
        if self._process is not None:
            self._process.join(timeout=5.0)
            if self._process.is_alive():
                self._process.terminate()

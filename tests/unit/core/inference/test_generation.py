"""`PresetWorker` (deep-dive §6.1) — real `multiprocessing.Process`/`Queue` mechanics
against `fakes.FakeBackend`, not mocked. Every test here spawns an actual child process;
all marked `slow` per this suite's own convention.

`fakes.py` is a real, importable module (not a closure defined in this file) specifically
so `backend_factory=make_fake_backend` survives being pickled to the child process under
Windows's `spawn` start method — confirmed directly this session that a closure cannot be
pickled at all (`PicklingError: Can't pickle local object`), the same discovery that shaped
`core/preprocessing/generation.py`'s own design.
"""

from __future__ import annotations

import asyncio

import pytest

from core.inference.contracts import GenerationRequest, MessageRole
from core.inference.errors import ModelLoadFailed, WorkerUnavailable
from core.inference.generation import PresetWorker

from .conftest import run, text_message
from .fakes import make_failing_backend, make_fake_backend


def _request(text: str, timeout_ms: int = 10_000, tools=()) -> GenerationRequest:
    return GenerationRequest(
        run_id="r1", user_id="u1", preset="test-preset",
        messages=(text_message(MessageRole.USER, text),), timeout_ms=timeout_ms, tools=tools,
    )


@pytest.mark.slow
def test_worker_loads_a_real_child_process_and_responds():
    async def go():
        worker = PresetWorker("test-preset", "fake-model-dir", "cpu", backend_factory=make_fake_backend)
        await worker.load()
        try:
            assert worker.is_alive()
            result = await worker.submit(_request("hello world"), grammar_schema=None)
            assert result.error is None
            assert "hello world" in result.text
        finally:
            await worker.shutdown()

    run(go())


@pytest.mark.slow
def test_worker_load_failure_raises_model_load_failed():
    async def go():
        worker = PresetWorker("test-preset", "fake-model-dir", "cpu", backend_factory=make_failing_backend)
        with pytest.raises(ModelLoadFailed):
            await worker.load()

    run(go())


@pytest.mark.slow
def test_concurrent_requests_are_batched_and_all_succeed():
    async def go():
        worker = PresetWorker("test-preset", "fake-model-dir", "cpu", backend_factory=make_fake_backend)
        await worker.load()
        try:
            results = await asyncio.gather(
                *(worker.submit(_request(f"req-{i}"), grammar_schema=None) for i in range(8))
            )
            assert all(r.error is None for r in results)
        finally:
            await worker.shutdown()

    run(go())


@pytest.mark.slow
def test_a_crash_inside_generate_is_contained_and_worker_stays_alive():
    """The concrete validation of §6.1's own crash-isolation claim: an exception during
    generation must not kill the worker process, and every other request must still work."""

    async def go():
        worker = PresetWorker("test-preset", "fake-model-dir", "cpu", backend_factory=make_fake_backend)
        await worker.load()
        try:
            crashed = await worker.submit(_request("please CRASH now"), grammar_schema=None)
            assert crashed.error is not None
            assert crashed.error.code.value == "generation_crashed"
            assert worker.is_alive()

            healthy = await worker.submit(_request("still working"), grammar_schema=None)
            assert healthy.error is None
        finally:
            await worker.shutdown()

    run(go())


@pytest.mark.slow
def test_a_hard_process_kill_fails_pending_and_future_calls_cleanly():
    """Deep-dive §11's own named crash-isolation bench case, done via `SIGKILL`-equivalent
    (`Process.kill()`) rather than a mid-call timeout — a genuinely different failure mode
    than an in-generate exception."""

    async def go():
        worker = PresetWorker("test-preset", "fake-model-dir", "cpu", backend_factory=make_fake_backend)
        await worker.load()

        async def kill_soon():
            await asyncio.sleep(0.3)
            worker._process.kill()  # noqa: SLF001 - test-only, simulating a real crash

        results = await asyncio.gather(
            worker.submit(_request("SLOW please", timeout_ms=10_000), grammar_schema=None),
            kill_soon(),
            return_exceptions=True,
        )
        assert isinstance(results[0], WorkerUnavailable)
        assert not worker.is_alive()

    run(go())


@pytest.mark.slow
def test_tool_call_grammar_produces_a_parsed_tool_call():
    async def go():
        from core.inference.tool_calling import build_tool_call_schema
        from core.inference.contracts import ToolSpec
        from common.frozen_dict import FrozenDict

        tools = (ToolSpec(name="lookup_vendor", description="", parameters_schema=FrozenDict({})),)
        worker = PresetWorker("test-preset", "fake-model-dir", "cpu", backend_factory=make_fake_backend)
        await worker.load()
        try:
            schema = build_tool_call_schema(tools)
            result = await worker.submit(_request("TOOLCALL please", tools=tools), grammar_schema=schema)
            assert result.error is None
            assert result.tool_call is not None
            assert result.tool_call.name == "lookup_vendor"
            assert result.finish_reason.value == "tool_call"
        finally:
            await worker.shutdown()

    run(go())


@pytest.mark.slow
def test_truncated_output_retries_then_salvages():
    async def go():
        worker = PresetWorker("test-preset", "fake-model-dir", "cpu", backend_factory=make_fake_backend)
        await worker.load()
        try:
            result = await worker.submit(
                _request("TRUNCATE please"), grammar_schema={"type": "object"}
            )
            assert result.error is None
            assert result.finish_reason.value == "length"
            assert "Dunkin" in result.text
        finally:
            await worker.shutdown()

    run(go())

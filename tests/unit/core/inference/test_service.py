"""The `InferenceServicer` gRPC surface (`inference.proto`).

`nox -s forward_compat` deliberately installs a narrow dependency set that excludes grpcio
(no prebuilt wheel for 3.15 yet, `docs/MAINTENANCE.md` §8.1) — the same guard `core/ocr/`'s
and `core/preprocessing/`'s own `test_service.py` modules already carry.

Exercised against a fake, in-process worker (`test_model_registry.py`'s own
`_FakeWorker`-shaped stand-in) rather than a real `onnxruntime_genai` model — this proves
the servicer's own message translation is correct, independent of whether real model
weights are ever downloaded in this environment.
"""

from __future__ import annotations

import asyncio

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.inference.contracts import FinishReason, GenerationResult  # noqa: E402
from core.inference.model_registry import InferenceConfig  # noqa: E402
from core.inference.service import InferenceServicer, serve  # noqa: E402


class _FakeWorker:
    def __init__(self, preset_name: str) -> None:
        self.preset_name = preset_name

    async def load(self) -> None:
        pass

    def is_alive(self) -> bool:
        return True

    async def submit(self, request, grammar_schema, images=()):
        return GenerationResult(
            text="hello from a fake worker", tool_call=None, finish_reason=FinishReason.STOP,
            schema_valid=True, device="cpu", duration_ms=1,
        )

    async def shutdown(self) -> None:
        pass


def _fake_worker_factory(name: str) -> _FakeWorker:
    return _FakeWorker(name)


@pytest.mark.slow
def test_generate_through_the_servicer_directly():
    async def go():
        config = InferenceConfig(presets_enabled=frozenset({"phi4-mini"}))
        servicer = InferenceServicer(config, worker_factory=_fake_worker_factory)
        from core.inference.generated import inference_pb2 as pb

        request = pb.GenerateRequest(
            run_id="r1", user_id="u1", preset="phi4-mini",
            messages=[pb.Message(role="user", content=[pb.ContentBlock(type="text", text="hi")])],
            max_tokens=100, timeout_ms=5000,
        )
        return await servicer.Generate(request)

    response = asyncio.run(go())
    assert response.error_code == ""
    assert response.text == "hello from a fake worker"
    assert response.finish_reason == "stop"


@pytest.mark.slow
def test_list_presets_reflects_the_real_registry():
    async def go():
        servicer = InferenceServicer(InferenceConfig())
        from core.inference.generated import inference_pb2 as pb

        return await servicer.ListPresets(pb.ListPresetsRequest())

    response = asyncio.run(go())
    assert "phi4-mini" in response.available_presets


@pytest.mark.slow
def test_a_real_client_can_generate_over_an_actual_grpc_connection():
    """No stub of the thing under test: a real `grpc.aio` server on a real loopback
    socket, a real client stub — matching `core/ocr/service.py`'s and
    `core/preprocessing/service.py`'s own real-connection tests."""
    from core.inference.generated import inference_pb2, inference_pb2_grpc

    async def go():
        address = "127.0.0.1:19712"
        config = InferenceConfig(presets_enabled=frozenset({"phi4-mini"}))
        server = await serve(address, config=config)
        try:
            channel = grpc.aio.insecure_channel(address)
            stub = inference_pb2_grpc.InferenceServiceStub(channel)
            response = await stub.ListPresets(inference_pb2.ListPresetsRequest())
            await channel.close()
            return response
        finally:
            await server.stop(None)

    response = asyncio.run(go())
    assert "phi4-mini" in response.available_presets

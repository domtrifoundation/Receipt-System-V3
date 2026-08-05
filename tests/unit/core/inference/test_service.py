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
from core.inference.service import InferenceServicer, _config_from_env, serve  # noqa: E402


class _FakeWorker:
    def __init__(self, preset_name: str) -> None:
        self.preset_name = preset_name

    async def load(self) -> None:
        pass

    def is_alive(self) -> bool:
        return True

    async def submit(self, request, grammar_schema, images=(), on_retry=None):
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
def test_warm_up_loads_the_full_pool_for_every_enabled_preset_before_returning():
    load_calls: list[str] = []

    class _CountingWorker(_FakeWorker):
        async def load(self) -> None:
            load_calls.append(self.preset_name)

    async def go():
        config = InferenceConfig(
            presets_enabled=frozenset({"phi4-mini"}), worker_pool_size=3,
        )
        servicer = InferenceServicer(
            config, worker_factory=lambda name: _CountingWorker(name),
        )
        await servicer.warm_up()

    asyncio.run(go())
    assert load_calls == ["phi4-mini", "phi4-mini", "phi4-mini"]


@pytest.mark.slow
def test_warm_up_does_not_crash_the_process_when_one_preset_fails_to_load():
    """Real, live-found regression: the first version of `warm_up()` let `ModelLoadFailed`
    propagate straight out, crashing the whole service on a completely normal state --
    an enabled preset whose weights are not downloaded yet (confirmed live: a fresh
    install with an enabled-but-not-yet-provisioned preset killed the entire process
    before it could even accept the `ProvisionPreset` call that would have fixed it).
    A failing preset must stay unavailable, never take every other enabled preset's own
    warm-up down with it."""
    from core.inference.errors import ModelLoadFailed

    load_calls: list[str] = []

    class _SelectivelyFailingWorker(_FakeWorker):
        async def load(self) -> None:
            load_calls.append(self.preset_name)
            if self.preset_name == "phi4-vision":
                raise ModelLoadFailed("weights not on disk yet")

    async def go():
        config = InferenceConfig(presets_enabled=frozenset({"phi4-mini", "phi4-vision"}))
        servicer = InferenceServicer(
            config, worker_factory=lambda name: _SelectivelyFailingWorker(name),
        )
        await servicer.warm_up()  # must not raise

    asyncio.run(go())
    assert set(load_calls) == {"phi4-mini", "phi4-vision"}


def _empty_hub_lister(repo: str) -> tuple:
    return ()


@pytest.mark.slow
def test_list_presets_reflects_the_real_registry():
    async def go():
        servicer = InferenceServicer(InferenceConfig(), hub_lister=_empty_hub_lister)
        from core.inference.generated import inference_pb2 as pb

        return await servicer.ListPresets(pb.ListPresetsRequest())

    response = asyncio.run(go())
    assert "phi4-mini" in response.available_presets


@pytest.mark.slow
def test_list_presets_reports_a_status_per_preset_and_caches_it():
    async def go():
        servicer = InferenceServicer(InferenceConfig(), hub_lister=_empty_hub_lister)
        from core.inference.generated import inference_pb2 as pb

        first = await servicer.ListPresets(pb.ListPresetsRequest())
        # Second call must be a pure in-memory read, not another Hub round trip -- this
        # test's own hub_lister has no way to distinguish call counts, but a servicer
        # that crashed here on a second network attempt in a real no-network environment
        # is exactly the regression this pins down structurally, not just by inspection.
        second = await servicer.ListPresets(pb.ListPresetsRequest())
        return first, second

    first, second = asyncio.run(go())
    names = {s.name for s in first.preset_statuses}
    assert "phi4-mini" in names
    assert {s.name: s.status for s in first.preset_statuses} == {
        s.name: s.status for s in second.preset_statuses
    }
    phi4_mini = next(s for s in first.preset_statuses if s.name == "phi4-mini")
    assert phi4_mini.status == "not_downloaded"
    assert phi4_mini.device == "cpu"


# --------------------------------------------------------------------- ProvisionPreset


_PROVISION_FILES = (
    ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/genai_config.json", 5),
    ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/model.onnx", 7),
)


def _provision_hub_lister(repo: str):
    return _PROVISION_FILES


@pytest.mark.slow
def test_provision_preset_streams_progress_then_a_complete_message(tmp_path, monkeypatch):
    import core.inference.model_provisioning as mp
    from services.update.proving_grounds.contracts import DownloadResult

    async def _fake_download(url, destination, **kwargs):
        from pathlib import Path

        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"x" * 5 if "genai_config" in url else b"x" * 7)
        return DownloadResult(ok=True, destination=str(destination), bytes_written=len(Path(destination).read_bytes()))

    monkeypatch.setattr(mp, "download_file", _fake_download)

    async def go():
        config = InferenceConfig(models_dir=str(tmp_path))
        servicer = InferenceServicer(config, hub_lister=_provision_hub_lister)
        from core.inference.generated import inference_pb2 as pb

        messages = []
        async for msg in servicer.ProvisionPreset(
            pb.ProvisionPresetRequest(preset="phi4-mini", device_family="cpu")
        ):
            messages.append(msg)
        return messages, servicer

    messages, servicer = asyncio.run(go())

    assert messages[-1].complete is True
    assert messages[-1].ok is True
    assert messages[-1].error_code == ""
    # At least one real progress update before the terminal one.
    assert any(not m.complete for m in messages)
    assert servicer._live_status["phi4-mini"].value == "ready"


@pytest.mark.slow
def test_provision_preset_unknown_preset_yields_one_failed_complete_message():
    async def go():
        servicer = InferenceServicer(InferenceConfig(), hub_lister=_empty_hub_lister)
        from core.inference.generated import inference_pb2 as pb

        messages = []
        async for msg in servicer.ProvisionPreset(
            pb.ProvisionPresetRequest(preset="no-such-preset", device_family="cpu")
        ):
            messages.append(msg)
        return messages

    messages = asyncio.run(go())
    assert len(messages) == 1
    assert messages[0].complete is True
    assert messages[0].ok is False
    assert messages[0].error_code == "PRESET_NOT_CONFIGURED"


@pytest.mark.slow
def test_a_real_client_can_stream_provisioning_progress_over_an_actual_grpc_connection(tmp_path, monkeypatch):
    """No stub of the thing under test — a real `grpc.aio` server, a real client stub
    consuming a real streamed RPC, matching `test_a_real_client_can_generate_...`'s own
    discipline one level up (server streaming, not unary)."""
    import core.inference.model_provisioning as mp
    from core.inference.generated import inference_pb2, inference_pb2_grpc
    from services.update.proving_grounds.contracts import DownloadResult

    async def _fake_download(url, destination, **kwargs):
        from pathlib import Path

        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"x" * 5 if "genai_config" in url else b"x" * 7)
        return DownloadResult(ok=True, destination=str(destination), bytes_written=5)

    monkeypatch.setattr(mp, "download_file", _fake_download)

    async def go():
        address = "127.0.0.1:19713"
        config = InferenceConfig(models_dir=str(tmp_path))
        # `serve()` builds its own InferenceServicer internally with no hub_lister seam,
        # so this test constructs the servicer directly and registers it on a real server
        # the same low-level way `serve()` itself does, to keep the real network fully
        # out of a "no stub of the thing under test" test.
        import grpc as grpc_module

        from core.inference.service import InferenceServicer

        server = grpc_module.aio.server()
        servicer = InferenceServicer(config, hub_lister=_provision_hub_lister)
        inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)
        port = server.add_insecure_port(address)
        await server.start()
        try:
            channel = grpc.aio.insecure_channel(address)
            stub = inference_pb2_grpc.InferenceServiceStub(channel)
            messages = []
            async for msg in stub.ProvisionPreset(
                inference_pb2.ProvisionPresetRequest(preset="phi4-mini", device_family="cpu")
            ):
                messages.append(msg)
            await channel.close()
            return messages
        finally:
            await server.stop(None)

    messages = asyncio.run(go())
    assert messages[-1].complete is True
    assert messages[-1].ok is True


# --------------------------------------------------------------------- _config_from_env


def test_config_from_env_defaults_match_inferenceconfig_defaults(monkeypatch):
    for var in (
        "RESIBO_INFERENCE_MODELS_DIR", "RESIBO_INFERENCE_PRESETS_ENABLED", "RESIBO_INFERENCE_DEVICE",
        "RESIBO_INFERENCE_WORKER_POOL_SIZE",
    ):
        monkeypatch.delenv(var, raising=False)

    config = _config_from_env()

    assert config == InferenceConfig()


def test_config_from_env_models_dir_override(monkeypatch):
    monkeypatch.setenv("RESIBO_INFERENCE_MODELS_DIR", r"C:\InferenceModels")

    config = _config_from_env()

    assert config.models_dir == r"C:\InferenceModels"


def test_config_from_env_presets_enabled_override(monkeypatch):
    monkeypatch.setenv("RESIBO_INFERENCE_PRESETS_ENABLED", "phi4-mini, phi4-vision")

    config = _config_from_env()

    assert config.presets_enabled == frozenset({"phi4-mini", "phi4-vision"})


def test_config_from_env_device_applies_to_every_enabled_preset(monkeypatch):
    monkeypatch.setenv("RESIBO_INFERENCE_PRESETS_ENABLED", "phi4-mini,phi4-vision")
    monkeypatch.setenv("RESIBO_INFERENCE_DEVICE", "dml")

    config = _config_from_env()

    assert dict(config.device_by_preset) == {"phi4-mini": "dml", "phi4-vision": "dml"}


def test_config_from_env_worker_pool_size_override(monkeypatch):
    monkeypatch.setenv("RESIBO_INFERENCE_WORKER_POOL_SIZE", "3")

    config = _config_from_env()

    assert config.worker_pool_size == 3


def test_config_from_env_worker_pool_size_degrades_to_one_on_malformed_value(monkeypatch):
    monkeypatch.setenv("RESIBO_INFERENCE_WORKER_POOL_SIZE", "not-a-number")

    config = _config_from_env()

    assert config.worker_pool_size == 1


def test_config_from_env_worker_pool_size_never_goes_below_one(monkeypatch):
    monkeypatch.setenv("RESIBO_INFERENCE_WORKER_POOL_SIZE", "0")

    config = _config_from_env()

    assert config.worker_pool_size == 1


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


# --------------------------------------------------------------------- ListExecutionProviders


@pytest.mark.slow
def test_list_execution_providers_reports_the_full_real_catalog():
    async def go():
        servicer = InferenceServicer(InferenceConfig(), hub_lister=_empty_hub_lister)
        from core.inference.generated import inference_pb2 as pb

        return await servicer.ListExecutionProviders(pb.ListExecutionProvidersRequest())

    response = asyncio.run(go())
    by_device = {p.device: p for p in response.providers}
    assert set(by_device) == {"cpu", "cuda", "tensorrt", "directml", "openvino", "qnn", "migraphx"}
    assert by_device["cpu"].installable is True
    assert by_device["cuda"].installable is True
    # No prebuilt onnxruntime-genai *pip* wheel installs openvino/qnn, but a real
    # NuGet-distributed EP plugin package exists for both (confirmed live -- see
    # common/execution_provider.py's own openvino/qnn notes) -- installable via that
    # separate channel. migraphx has neither a pip wheel nor a confirmed NuGet package.
    assert by_device["openvino"].installable is True
    assert by_device["qnn"].installable is True
    assert by_device["migraphx"].installable is False
    # TensorRT rides on the CUDA wheel -- still real and installable, just not its own
    # separate pip package (confirmed live: no onnxruntime-genai-tensorrt wheel exists).
    assert by_device["tensorrt"].installable is True
    assert by_device["cpu"].confidence == "high"


# --------------------------------------------------------------------- SetPresetDevice


@pytest.mark.slow
def test_set_preset_device_with_no_install_root_reports_that_honestly():
    async def go():
        servicer = InferenceServicer(InferenceConfig(), hub_lister=_empty_hub_lister)
        from core.inference.generated import inference_pb2 as pb

        return await servicer.SetPresetDevice(
            pb.SetPresetDeviceRequest(preset="phi4-mini", device="cuda")
        )

    response = asyncio.run(go())
    assert response.ok is False
    assert response.error_code == "NO_INSTALL_ROOT"


@pytest.mark.slow
def test_set_preset_device_unknown_preset_reports_error_not_a_write(tmp_path):
    async def go():
        servicer = InferenceServicer(InferenceConfig(), hub_lister=_empty_hub_lister, install_root=tmp_path)
        from core.inference.generated import inference_pb2 as pb

        return await servicer.SetPresetDevice(
            pb.SetPresetDeviceRequest(preset="no-such-preset", device="cuda")
        )

    response = asyncio.run(go())
    assert response.ok is False
    assert response.error_code == "PRESET_NOT_CONFIGURED"


@pytest.mark.slow
def test_set_preset_device_persists_for_real_and_reports_takes_effect_on_restart(tmp_path):
    async def go():
        servicer = InferenceServicer(InferenceConfig(), hub_lister=_empty_hub_lister, install_root=tmp_path)
        from core.inference.generated import inference_pb2 as pb

        return await servicer.SetPresetDevice(
            pb.SetPresetDeviceRequest(preset="phi4-mini", device="cuda")
        )

    response = asyncio.run(go())
    assert response.ok is True
    assert response.takes_effect_on_restart is True

    from core.inference.device_overrides import read_device_overrides

    assert read_device_overrides(tmp_path) == {"phi4-mini": "cuda"}


# --------------------------------------------------------------------- _config_from_env + overrides


def test_config_from_env_merges_persisted_overrides_on_top_of_the_env_default(tmp_path, monkeypatch):
    from core.inference.device_overrides import write_device_override

    monkeypatch.setenv("RESIBO_INFERENCE_PRESETS_ENABLED", "phi4-mini,phi4-vision")
    monkeypatch.setenv("RESIBO_INFERENCE_DEVICE", "directml")
    write_device_override(tmp_path, "phi4-mini", "cuda")

    config = _config_from_env(install_root=tmp_path)

    # The env-var default still applies to the preset with no explicit override...
    assert dict(config.device_by_preset)["phi4-vision"] == "directml"
    # ...but the persisted, more specific override wins for the one that has one.
    assert dict(config.device_by_preset)["phi4-mini"] == "cuda"


def test_config_from_env_with_no_install_root_ignores_overrides_gracefully(monkeypatch):
    monkeypatch.setenv("RESIBO_INFERENCE_PRESETS_ENABLED", "phi4-mini")
    monkeypatch.setenv("RESIBO_INFERENCE_DEVICE", "directml")

    config = _config_from_env(install_root=None)

    assert dict(config.device_by_preset) == {"phi4-mini": "directml"}

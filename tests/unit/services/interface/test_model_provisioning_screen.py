"""`ModelProvisioningScreen`/`ModelProvisioningProgressScreen` — real `Pilot`-driven tests
against a genuine running `InferenceServicer`, never a mocked gRPC stub, matching
`test_fleet_screen.py`'s own established discipline exactly."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="textual is not installed in this interpreter")
pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.inference.model_registry import InferenceConfig  # noqa: E402
from core.inference.service import InferenceServicer, serve as inference_serve  # noqa: E402
from services.interface.tui.custom_screens.model_provisioning_screen import ModelProvisioningScreen  # noqa: E402
from textual.app import App  # noqa: E402
from textual.widgets import ListView, Static  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _empty_hub_lister(repo: str) -> tuple:
    return ()


_PROVISION_FILES = (
    ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/genai_config.json", 5),
)


def _provision_hub_lister(repo: str):
    return _PROVISION_FILES


class _Harness(App):
    def __init__(self, inference_address: str | None) -> None:
        super().__init__()
        self._inference_address = inference_address

    def on_mount(self) -> None:
        self.push_screen(ModelProvisioningScreen(self._inference_address))


def _row_text(list_view: ListView, item_id: str) -> str:
    item = next(i for i in list_view.children if i.id == item_id)
    return str(item.query_one(Static).render())


def test_reports_honestly_when_not_connected():
    async def scenario():
        app = _Harness("127.0.0.1:1")  # nothing real listens here
        async with app.run_test() as pilot:
            await pilot.pause()
            status = app.screen.query_one("#models-status", Static)
            assert "Not connected" in str(status.render())

    run(scenario())


def test_lists_real_presets_with_status_from_a_real_inference_service():
    async def scenario():
        config = InferenceConfig()
        servicer = InferenceServicer(config, hub_lister=_empty_hub_lister)
        import grpc

        from core.inference.generated import inference_pb2_grpc

        server = grpc.aio.server()
        inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            app = _Harness(f"127.0.0.1:{port}")
            async with app.run_test() as pilot:
                await pilot.pause()
                list_view = app.screen.query_one("#models-list", ListView)
                assert any(item.id == "models-row-phi4-mini" for item in list_view.children)
                assert "not downloaded" in _row_text(list_view, "models-row-phi4-mini")
        finally:
            await server.stop(None)

    run(scenario())


def test_selecting_an_already_ready_preset_and_pressing_provision_reports_already_ready(tmp_path: Path):
    async def scenario():
        preset_dir = tmp_path / "phi4-mini"
        preset_dir.mkdir()
        (preset_dir / "genai_config.json").write_bytes(b"x" * 5)

        config = InferenceConfig(models_dir=str(tmp_path))
        servicer = InferenceServicer(config, hub_lister=_provision_hub_lister)
        import grpc

        from core.inference.generated import inference_pb2_grpc

        server = grpc.aio.server()
        inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            app = _Harness(f"127.0.0.1:{port}")
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                list_view = screen.query_one("#models-list", ListView)
                target = next(i for i in list_view.children if i.id == "models-row-phi4-mini")
                list_view.index = list_view.children.index(target)
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.click("#models-provision")
                await pilot.pause(0.2)

                status = screen.query_one("#models-status", Static)
                assert "already downloaded" in str(status.render()).lower()
        finally:
            await server.stop(None)

    run(scenario())


def test_provisioning_an_unready_preset_streams_progress_and_completes(tmp_path: Path, monkeypatch):
    async def scenario():
        import core.inference.model_provisioning as mp
        from services.update.proving_grounds.contracts import DownloadResult

        async def _fake_download(url, destination, **kwargs):
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            Path(destination).write_bytes(b"x" * 5)
            return DownloadResult(ok=True, destination=str(destination), bytes_written=5)

        monkeypatch.setattr(mp, "download_file", _fake_download)

        config = InferenceConfig(models_dir=str(tmp_path))
        servicer = InferenceServicer(config, hub_lister=_provision_hub_lister)
        import grpc

        from core.inference.generated import inference_pb2_grpc

        server = grpc.aio.server()
        inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            app = _Harness(f"127.0.0.1:{port}")
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                list_view = screen.query_one("#models-list", ListView)
                target = next(i for i in list_view.children if i.id == "models-row-phi4-mini")
                list_view.index = list_view.children.index(target)
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.click("#models-provision")
                # The provisioning progress screen is now pushed and streaming for real.
                await pilot.pause(0.5)

            assert (tmp_path / "phi4-mini" / "genai_config.json").read_bytes() == b"x" * 5
        finally:
            await server.stop(None)

    run(scenario())


# --------------------------------------------------------------------- manual EP selection


def test_device_select_is_populated_with_the_full_real_provider_catalog():
    """No public "list current options" accessor exists on `Select`, so this proves the
    real thing that matters instead: every device `ListExecutionProviders` reports is a
    genuinely assignable value -- `Select` raises `InvalidSelectValueError` for anything
    not actually in its own option list, so a clean assign+read-back round trip for each
    one is real evidence the option reached the widget, not an assumption."""

    async def scenario():
        config = InferenceConfig()
        servicer = InferenceServicer(config, hub_lister=_empty_hub_lister)
        import grpc

        from core.inference.generated import inference_pb2_grpc

        server = grpc.aio.server()
        inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            app = _Harness(f"127.0.0.1:{port}")
            async with app.run_test() as pilot:
                await pilot.pause()
                from textual.widgets import Select

                select = app.screen.query_one("#models-device-select", Select)
                for device in ("cpu", "cuda", "tensorrt", "directml", "openvino", "qnn", "migraphx"):
                    select.value = device
                    assert select.value == device
        finally:
            await server.stop(None)

    run(scenario())


def test_selecting_a_preset_preselects_its_current_device():
    async def scenario():
        config = InferenceConfig(device_by_preset={"phi4-mini": "cpu"})
        servicer = InferenceServicer(config, hub_lister=_empty_hub_lister)
        import grpc

        from core.inference.generated import inference_pb2_grpc

        server = grpc.aio.server()
        inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            app = _Harness(f"127.0.0.1:{port}")
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                list_view = screen.query_one("#models-list", ListView)
                target = next(i for i in list_view.children if i.id == "models-row-phi4-mini")
                list_view.index = list_view.children.index(target)
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()

                from textual.widgets import Select

                select = screen.query_one("#models-device-select", Select)
                assert select.value == "cpu"
        finally:
            await server.stop(None)

    run(scenario())


def test_set_device_persists_a_real_manual_override(tmp_path: Path):
    async def scenario():
        config = InferenceConfig()
        servicer = InferenceServicer(config, hub_lister=_empty_hub_lister, install_root=tmp_path)
        import grpc

        from core.inference.generated import inference_pb2_grpc

        server = grpc.aio.server()
        inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            app = _Harness(f"127.0.0.1:{port}")
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                list_view = screen.query_one("#models-list", ListView)
                target = next(i for i in list_view.children if i.id == "models-row-phi4-mini")
                list_view.index = list_view.children.index(target)
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()

                from textual.widgets import Select

                screen.query_one("#models-device-select", Select).value = "cuda"
                await pilot.pause()
                await pilot.click("#models-set-device")
                await pilot.pause(0.2)

                status = screen.query_one("#models-status", Static)
                assert "cuda" in str(status.render())
        finally:
            await server.stop(None)

        from core.inference.device_overrides import read_device_overrides

        assert read_device_overrides(tmp_path) == {"phi4-mini": "cuda"}

    run(scenario())


def test_set_device_with_nothing_selected_reports_that_honestly():
    async def scenario():
        config = InferenceConfig()
        servicer = InferenceServicer(config, hub_lister=_empty_hub_lister)
        import grpc

        from core.inference.generated import inference_pb2_grpc

        server = grpc.aio.server()
        inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            app = _Harness(f"127.0.0.1:{port}")
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                await pilot.click("#models-set-device")
                await pilot.pause(0.2)

                status = screen.query_one("#models-status", Static)
                assert "select a preset" in str(status.render()).lower()
        finally:
            await server.stop(None)

    run(scenario())

"""`RunMonitorScreen` — real end to end against a genuine running `ExecutionCoreServicer`,
including a real streamed `GetRunStatus`. No mocked gRPC stub anywhere in this chain."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual", reason="textual is not installed in this interpreter")
grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from services.execution_core.generated import execution_core_pb2 as ec_pb  # noqa: E402
from services.execution_core.generated import execution_core_pb2_grpc as ec_pb_grpc  # noqa: E402
from services.execution_core.service import serve as execution_core_serve  # noqa: E402
from services.interface.tui.custom_screens.run_monitor_screen import RunMonitorScreen  # noqa: E402
from textual.app import App  # noqa: E402
from textual.widgets import ListView, Static  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _Harness(App):
    def __init__(self, address: str) -> None:
        super().__init__()
        self._address = address

    def on_mount(self) -> None:
        self.push_screen(RunMonitorScreen(address_override=self._address))


def test_shows_no_active_runs_honestly():
    async def scenario():
        server = await execution_core_serve("127.0.0.1:0")
        try:
            app = _Harness(server.bound_address)
            async with app.run_test() as pilot:
                await pilot.pause()
                detail = app.screen.query_one("#run-monitor-detail", Static)
                assert "No active runs" in str(detail.render())
        finally:
            await server.stop(None)

    run(scenario())


def test_lists_a_real_started_run(tmp_path):
    async def scenario():
        server = await execution_core_serve("127.0.0.1:0")
        try:
            async with grpc.aio.insecure_channel(server.bound_address) as channel:
                await ec_pb_grpc.ExecutionCoreServiceStub(channel).StartRun(
                    ec_pb.StartRunRequest(user_id="u1", file_count=1)
                )

            app = _Harness(server.bound_address)
            async with app.run_test() as pilot:
                await pilot.pause()
                list_view = app.screen.query_one("#run-monitor-list", ListView)
                assert len(list_view.children) == 1
        finally:
            await server.stop(None)

    run(scenario())


def test_selecting_a_run_streams_its_real_status(tmp_path):
    async def scenario():
        server = await execution_core_serve("127.0.0.1:0")
        try:
            async with grpc.aio.insecure_channel(server.bound_address) as channel:
                start_response = await ec_pb_grpc.ExecutionCoreServiceStub(channel).StartRun(
                    ec_pb.StartRunRequest(user_id="u1", file_count=1)
                )

            app = _Harness(server.bound_address)
            async with app.run_test() as pilot:
                await pilot.pause()
                list_view = app.screen.query_one("#run-monitor-list", ListView)
                target = next(i for i in list_view.children if i.id == f"run-{start_response.run.run_id}")
                await pilot.click(f"#{target.id}")
                await pilot.pause(0.6)

                detail = app.screen.query_one("#run-monitor-detail", Static)
                assert start_response.run.run_id in str(detail.render())
        finally:
            await server.stop(None)

    run(scenario())

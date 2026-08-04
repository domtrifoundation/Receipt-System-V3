"""`MonitorScreen` — the real landing screen. Live `Pilot`-driven tests against a genuine
running `SupervisorServicer`, never a mocked gRPC stub."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="textual is not installed in this interpreter")

from services.interface.tui.custom_screens.monitor_screen import MonitorScreen  # noqa: E402
from supervisor.arbitration import ChannelArbitrator  # noqa: E402
from supervisor.contracts import ServiceLaunchResult  # noqa: E402
from supervisor.service import serve as supervisor_serve  # noqa: E402
from textual.app import App  # noqa: E402
from textual.widgets import Static  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _Harness(App):
    def __init__(self, supervisor_address: str | None, channel: str = "beta") -> None:
        super().__init__()
        self._supervisor_address = supervisor_address
        self._channel = channel
        self.opened_menu = False

    def on_mount(self) -> None:
        self.push_screen(MonitorScreen(self._supervisor_address, self._channel, on_open_menu=self._open_menu))

    def _open_menu(self) -> None:
        self.opened_menu = True


def test_reports_honestly_when_not_connected():
    async def scenario():
        app = _Harness(None)
        async with app.run_test() as pilot:
            await pilot.pause()
            release_panel = app.screen.query_one("#monitor-release", Static)
            assert "Not connected" in str(release_panel.render())

    run(scenario())


def test_reports_no_active_release_honestly(tmp_path: Path):
    async def scenario():
        server = await supervisor_serve(install_root=tmp_path, specs={})
        try:
            app = _Harness(server.bound_address, "beta")
            async with app.run_test() as pilot:
                await pilot.pause()
                release_panel = app.screen.query_one("#monitor-release", Static)
                assert "UNKNOWN_CHANNEL" in str(release_panel.render()) or "no active release" in str(release_panel.render())
        finally:
            await server.stop(grace=1.0)

    run(scenario())


def test_shows_real_service_states_from_a_real_active_release(tmp_path: Path):
    REPO_ROOT = Path(__file__).resolve().parents[4]

    async def scenario():
        server = await supervisor_serve(install_root=tmp_path, specs={})
        try:
            ChannelArbitrator(tmp_path).set_active("beta", REPO_ROOT)

            app = _Harness(server.bound_address, "beta")
            async with app.run_test() as pilot:
                await pilot.pause()
                release_panel = app.screen.query_one("#monitor-release", Static)
                assert "beta" in str(release_panel.render())
                services_panel = app.screen.query_one("#monitor-services", Static)
                # A real fleet discovery ran against the real repo checkout -- some real
                # service count shows, not a fabricated placeholder number.
                assert "Services (" in str(services_panel.render())
        finally:
            await server.stop(grace=1.0)

    run(scenario())


def test_shows_real_running_instances(tmp_path: Path):
    REPO_ROOT = Path(__file__).resolve().parents[4]

    async def scenario():
        server = await supervisor_serve(install_root=tmp_path, specs={})
        try:
            ChannelArbitrator(tmp_path).set_active("beta", REPO_ROOT)
            server.servicer._instances.record("ocr", "x03.01.05", ServiceLaunchResult(name="ocr", ok=True, pid=123, address="127.0.0.1:59991"))

            app = _Harness(server.bound_address, "beta")
            async with app.run_test() as pilot:
                await pilot.pause()
                instances_panel = app.screen.query_one("#monitor-instances", Static)
                text = str(instances_panel.render())
                assert "ocr" in text
                assert "x03.01.05" in text
        finally:
            await server.stop(grace=1.0)

    run(scenario())


def test_runs_panel_is_honest_about_the_real_execution_core_gap():
    async def scenario():
        app = _Harness(None)
        async with app.run_test() as pilot:
            await pilot.pause()
            runs_panel = app.screen.query_one("#monitor-runs", Static)
            assert "not available" in str(runs_panel.render())

    run(scenario())


def test_pressing_m_opens_the_menu():
    async def scenario():
        app = _Harness(None)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            assert app.opened_menu is True

    run(scenario())


def test_pressing_r_refreshes_without_error(tmp_path: Path):
    async def scenario():
        server = await supervisor_serve(install_root=tmp_path, specs={})
        try:
            app = _Harness(server.bound_address, "beta")
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                release_panel = app.screen.query_one("#monitor-release", Static)
                assert str(release_panel.render()) != ""
        finally:
            await server.stop(grace=1.0)

    run(scenario())

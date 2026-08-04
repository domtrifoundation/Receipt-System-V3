"""`FleetScreen` — a real `Pilot`-driven test against a genuine running `SupervisorServicer`,
never a mocked gRPC stub. Confirms the multi-version editor calls `SetAvailableVersions`
for real, and that `interface_tui`/`inference` show the single-instance tag."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="textual is not installed in this interpreter")

from services.interface.tui.custom_screens.fleet_screen import FleetScreen  # noqa: E402
from supervisor.service import serve as supervisor_serve  # noqa: E402
from textual.app import App  # noqa: E402
from textual.widgets import Input, ListView, Static  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _Harness(App):
    def __init__(self, supervisor_address: str | None, channel: str = "beta") -> None:
        super().__init__()
        self._supervisor_address = supervisor_address
        self._channel = channel

    def on_mount(self) -> None:
        self.push_screen(FleetScreen(self._supervisor_address, self._channel))


def _row_text(list_view: ListView, item_id: str) -> str:
    item = next(i for i in list_view.children if i.id == item_id)
    return str(item.query_one(Static).render())


def test_reports_honestly_when_not_connected():
    async def scenario():
        app = _Harness(None, "beta")
        async with app.run_test() as pilot:
            await pilot.pause()
            status = app.screen.query_one("#fleet-status", Static)
            assert "Not connected" in str(status.render())

    run(scenario())


def test_lists_available_versions_from_a_real_supervisor(tmp_path: Path):
    async def scenario():
        server = await supervisor_serve(install_root=tmp_path, specs={})
        try:
            server.servicer._available_versions.set_available("beta", "ocr", ("x03.01.05", "x03.01.06"))

            app = _Harness(server.bound_address, "beta")
            async with app.run_test() as pilot:
                await pilot.pause()
                list_view = app.screen.query_one("#fleet-list", ListView)
                assert any(item.id == "fleet-row-ocr" for item in list_view.children)
                assert "2 available" in _row_text(list_view, "fleet-row-ocr")
        finally:
            await server.stop(grace=1.0)

    run(scenario())


def test_editing_available_versions_calls_set_available_versions_for_real(tmp_path: Path):
    async def scenario():
        server = await supervisor_serve(install_root=tmp_path, specs={})
        try:
            server.servicer._available_versions.set_available("beta", "ocr", ("x03.01.05",))

            app = _Harness(server.bound_address, "beta")
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                list_view = screen.query_one("#fleet-list", ListView)
                target = next(i for i in list_view.children if i.id == "fleet-row-ocr")
                list_view.index = list_view.children.index(target)
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()

                version_input = screen.query_one("#fleet-version-input", Input)
                version_input.value = "x03.01.05, x03.01.07"
                await pilot.click("#fleet-apply")
                await pilot.pause(0.3)

            assert server.servicer._available_versions.get_available("beta", "ocr") == ("x03.01.05", "x03.01.07")
        finally:
            await server.stop(grace=1.0)

    run(scenario())


def test_single_instance_service_shows_the_single_instance_tag(tmp_path: Path):
    async def scenario():
        server = await supervisor_serve(install_root=tmp_path, specs={})
        try:
            server.servicer._available_versions.set_available("beta", "interface_tui", ("x03.01.05", "x03.01.06"))

            app = _Harness(server.bound_address, "beta")
            async with app.run_test() as pilot:
                await pilot.pause()
                list_view = app.screen.query_one("#fleet-list", ListView)
                text = _row_text(list_view, "fleet-row-interface_tui")
                assert "single-instance" in text
                # AvailableVersionsStore itself truncates to one -- confirms the real
                # end-to-end enforcement is visible in this screen's own rendered data,
                # not just at the store layer.
                assert "1 available" in text
        finally:
            await server.stop(grace=1.0)

    run(scenario())

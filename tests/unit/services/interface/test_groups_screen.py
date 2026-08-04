"""`GroupsScreen` — real end to end against genuine running `AuthServicer`/
`GroupsServicer` instances, single-tenant implicit-owner session. No mocked gRPC stub
anywhere in this chain."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual", reason="textual is not installed in this interpreter")
grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.auth.assembly import build_servicer  # noqa: E402
from core.auth.service import serve as auth_serve  # noqa: E402
from core.groups.auth_client import GrpcSessionResolver  # noqa: E402
from core.groups.service import serve as groups_serve  # noqa: E402
from services.interface.tui.custom_screens.groups_screen import GroupsScreen  # noqa: E402
from textual.app import App  # noqa: E402
from textual.widgets import Input, ListView, Static  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _Harness(App):
    def __init__(self, auth_address: str, groups_address: str) -> None:
        super().__init__()
        self._auth_address = auth_address
        self._groups_address = groups_address

    def on_mount(self) -> None:
        self.push_screen(GroupsScreen(auth_address_override=self._auth_address, groups_address_override=self._groups_address))


async def _start_servers():
    auth_servicer = build_servicer({"tenancy_mode": "single"})
    auth_server = await auth_serve(auth_servicer, "127.0.0.1:0")
    groups_server = groups_serve("127.0.0.1:0", resolver=GrpcSessionResolver(auth_server.bound_address))
    await groups_server.start()
    return auth_server, groups_server


def test_creating_a_group_works_end_to_end():
    async def scenario():
        auth_server, groups_server = await _start_servers()
        try:
            app = _Harness(auth_server.bound_address, groups_server.bound_address)
            async with app.run_test() as pilot:
                await pilot.pause()
                name_input = app.screen.query_one("#groups-new-name", Input)
                name_input.value = "Family"
                await pilot.click("#groups-create")
                await pilot.pause(0.3)

                status = app.screen.query_one("#groups-status", Static)
                assert "Created group" in str(status.render())
                group_id_input = app.screen.query_one("#groups-group-id", Input)
                assert group_id_input.value
        finally:
            await auth_server.stop(None)
            await groups_server.stop(None)

    run(scenario())


def test_add_member_then_load_shows_the_real_member():
    async def scenario():
        auth_server, groups_server = await _start_servers()
        try:
            app = _Harness(auth_server.bound_address, groups_server.bound_address)
            async with app.run_test() as pilot:
                await pilot.pause()
                app.screen.query_one("#groups-new-name", Input).value = "Team"
                await pilot.click("#groups-create")
                await pilot.pause(0.3)

                app.screen.query_one("#groups-member-id", Input).value = "client-1"
                await pilot.click("#groups-add-member")
                await pilot.pause(0.3)

                members = app.screen.query_one("#groups-members", ListView)
                assert any(i.id == "member-client-1" for i in members.children)
        finally:
            await auth_server.stop(None)
            await groups_server.stop(None)

    run(scenario())


def test_toggle_manager_flips_the_real_flag():
    async def scenario():
        auth_server, groups_server = await _start_servers()
        try:
            app = _Harness(auth_server.bound_address, groups_server.bound_address)
            # A real terminal-height issue this test itself caught live: the default
            # 80x24 test size clips this screen's own bottom controls, and a click
            # computed for an off-screen widget's position lands on the Footer's own
            # binding hint instead (silently triggering "Back"). A taller viewport is
            # the honest fix, matching what a real operator would need too.
            async with app.run_test(size=(80, 50)) as pilot:
                await pilot.pause()
                app.screen.query_one("#groups-new-name", Input).value = "Team"
                await pilot.click("#groups-create")
                await pilot.pause(0.3)

                app.screen.query_one("#groups-member-id", Input).value = "client-1"
                await pilot.click("#groups-add-member")
                await pilot.pause(0.3)

                await pilot.click("#groups-toggle-manager")
                await pilot.pause(0.3)

                members = app.screen.query_one("#groups-members", ListView)
                item = next(i for i in members.children if i.id == "member-client-1")
                assert "manager" in str(item.query_one(Static).render())
        finally:
            await auth_server.stop(None)
            await groups_server.stop(None)

    run(scenario())


def test_reports_honestly_when_no_session_is_available():
    async def scenario():
        auth_servicer = build_servicer({"tenancy_mode": "multi"})
        auth_server = await auth_serve(auth_servicer, "127.0.0.1:0")
        groups_server = groups_serve("127.0.0.1:0", resolver=GrpcSessionResolver(auth_server.bound_address))
        await groups_server.start()
        try:
            app = _Harness(auth_server.bound_address, groups_server.bound_address)
            async with app.run_test() as pilot:
                await pilot.pause()
                status = app.screen.query_one("#groups-status", Static)
                assert "No session available" in str(status.render())
        finally:
            await auth_server.stop(None)
            await groups_server.stop(None)

    run(scenario())

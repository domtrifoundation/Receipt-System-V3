"""`InterfaceApp` — real Textual `Pilot`-driven tests, never a mocked screen tree. Boot
tests launch a genuine `core/geo_address/service.py` subprocess via `boot_many()`, same as
Supervisor's own tests.

Plain `asyncio.run()` wrapping, matching this repo's own convention (`tests/unit/
supervisor/conftest.py`'s `run()`) rather than adding a `pytest-asyncio` dependency for
one test file.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="textual is not installed in this interpreter")

from services.interface.tui.app import InterfaceApp  # noqa: E402
from services.interface.tui.custom_screens.credits import CreditsScreen  # noqa: E402
from services.interface.tui.menu_screen import MenuScreen  # noqa: E402
from supervisor.contracts import ServiceSpec  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]


def run(coro):
    return asyncio.run(coro)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_launch_without_boot_specs_goes_straight_to_the_root_menu():
    async def scenario():
        app = InterfaceApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MenuScreen)

    run(scenario())


def test_selecting_credits_pushes_the_real_credits_screen():
    async def scenario():
        app = InterfaceApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.screen.query_one("#menu-list")
            credits_index = next(i for i, item in enumerate(list_view.children) if item.id == "item-credits")
            list_view.index = credits_index
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, CreditsScreen)

    run(scenario())


def test_selecting_an_unbuilt_custom_screen_reports_honestly_rather_than_crashing():
    async def scenario():
        app = InterfaceApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.screen.query_one("#menu-list")
            target_index = next(i for i, item in enumerate(list_view.children) if item.id == "item-run_monitor")
            list_view.index = target_index
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            tooltip = app.screen.query_one("#menu-tooltip")
            assert "isn't built yet" in str(tooltip.render())

    run(scenario())


def test_settings_submenu_navigates_and_back_returns_to_root():
    async def scenario():
        app = InterfaceApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.screen.query_one("#menu-list")
            list_view.index = next(i for i, item in enumerate(list_view.children) if item.id == "item-settings")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, MenuScreen)
            assert app.screen._title == "Settings"

            await pilot.press("escape")
            await pilot.pause()
            assert app.screen._title != "Settings"

    run(scenario())


def test_boot_sequence_screen_boots_a_real_service_then_reaches_the_root_menu():
    pids: list[int] = []

    async def scenario():
        spec = ServiceSpec(
            name="geo_address", import_path="core.geo_address", serve_module="core.geo_address.service",
            address=f"127.0.0.1:{_free_port()}",
        )
        app = InterfaceApp(boot_specs=(spec,), clone_dir=REPO_ROOT, channel="dev")
        async with app.run_test() as pilot:
            for _ in range(60):
                await pilot.pause(0.5)
                if isinstance(app.screen, MenuScreen):
                    break
            assert isinstance(app.screen, MenuScreen)

    try:
        run(scenario())
    finally:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

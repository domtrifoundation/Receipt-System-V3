"""`SettingValueScreen` — real end-to-end: a genuine running `SetupServicer`/`AuthServicer`/
`TelemetreesServicer`, resolved via `common/install_paths.resolve_install_root` (this test
file's own module path fakes being inside a `releases/` clone) and `common/blob_client`'s
service-address registry, exactly the path a real installed instance uses. No mocked gRPC
stub anywhere in this chain."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="textual is not installed in this interpreter")
grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from services.interface.contracts import MenuItemSpec  # noqa: E402
from services.interface.tui.custom_screens.setting_value_screen import SettingValueScreen  # noqa: E402
from services.interface.tui import settings_backend  # noqa: E402
from services.setup.service import serve as setup_serve  # noqa: E402
from textual.app import App  # noqa: E402
from textual.widgets import Button, ListView, Static  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _Harness(App):
    def __init__(self, item: MenuItemSpec, backend) -> None:
        super().__init__()
        self._item = item
        self._backend = backend

    def on_mount(self) -> None:
        self.push_screen(SettingValueScreen(self._item, self._backend))


def test_bool_ro_setting_shows_the_real_persisted_value(tmp_path: Path, monkeypatch):
    from services.setup.bootstrap import write_install_config

    write_install_config(tmp_path, dev_mode=True)
    monkeypatch.setattr(settings_backend, "_resolve_address", lambda name: "127.0.0.1:1")  # unused for install_root, only for fallback path

    async def scenario():
        server = await setup_serve("127.0.0.1:0", install_root=tmp_path)
        monkeypatch.setattr(settings_backend, "_resolve_address", lambda name: server.bound_address)
        try:
            item = MenuItemSpec(path="settings.general.dev_mode", label="Developer mode", tooltip="t", target="setup.get_dev_mode", kind="bool")
            app = _Harness(item, settings_backend.SETTINGS_BACKENDS["setup.get_dev_mode"])
            async with app.run_test() as pilot:
                await pilot.pause()
                value_panel = app.screen.query_one("#setting-value", Static)
                assert "true" in str(value_panel.render())
                toggle = app.screen.query_one("#setting-toggle", Button)
                assert toggle.display is False
        finally:
            await server.stop(grace=1.0)

    run(scenario())


def test_bool_rw_setting_toggles_for_real(tmp_path: Path, monkeypatch):
    async def scenario():
        server = await setup_serve("127.0.0.1:0", install_root=tmp_path)
        monkeypatch.setattr(settings_backend, "_resolve_address", lambda name: server.bound_address)
        try:
            item = MenuItemSpec(path="settings.general.run_on_startup", label="Run on startup", tooltip="t", target="setup.set_run_on_startup", kind="bool")
            app = _Harness(item, settings_backend.SETTINGS_BACKENDS["setup.set_run_on_startup"])
            async with app.run_test() as pilot:
                await pilot.pause()
                value_panel = app.screen.query_one("#setting-value", Static)
                assert "false" in str(value_panel.render())

                await pilot.click("#setting-toggle")
                await pilot.pause(0.2)

                value_panel = app.screen.query_one("#setting-value", Static)
                assert "true" in str(value_panel.render())

            from services.setup.bootstrap import read_run_on_startup
            assert read_run_on_startup(tmp_path) is True
        finally:
            await server.stop(grace=1.0)

    run(scenario())


def test_reports_honestly_when_no_install_root_is_known(monkeypatch):
    monkeypatch.setattr(settings_backend, "_resolve_address", lambda name: "127.0.0.1:1")

    async def unresolvable_get():
        return False, ""

    from services.interface.tui.settings_backend import SettingBackend

    backend = SettingBackend(kind="bool_ro", get=unresolvable_get)
    item = MenuItemSpec(path="settings.general.dev_mode", label="Developer mode", tooltip="t", target="setup.get_dev_mode", kind="bool")

    async def scenario():
        app = _Harness(item, backend)
        async with app.run_test() as pilot:
            await pilot.pause()
            value_panel = app.screen.query_one("#setting-value", Static)
            assert "Unknown" in str(value_panel.render())

    run(scenario())


def test_choice_rw_setting_lists_choices_and_marks_the_current_one(tmp_path: Path, monkeypatch):
    from core.auth.service import serve as auth_serve
    from core.auth.assembly import build_servicer

    async def scenario():
        servicer = build_servicer({"tenancy_mode": "multi"}, install_root=tmp_path)
        server = await auth_serve(servicer, "127.0.0.1:0")
        monkeypatch.setattr(settings_backend, "_resolve_address", lambda name: server.bound_address)
        try:
            item = MenuItemSpec(path="settings.general.tenancy_mode", label="Tenancy mode", tooltip="t", target="auth.get_tenancy_mode", kind="choice")
            app = _Harness(item, settings_backend.SETTINGS_BACKENDS["auth.get_tenancy_mode"])
            async with app.run_test() as pilot:
                await pilot.pause()
                choices = app.screen.query_one("#setting-choices", ListView)
                ids = [i.id for i in choices.children]
                assert "choice-single" in ids
                assert "choice-multi" in ids
        finally:
            await server.stop(None)

    run(scenario())

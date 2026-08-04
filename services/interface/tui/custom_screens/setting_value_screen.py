"""The real settings value-editor screen — previously missing entirely: selecting *any*
setting leaf, real backend or not, only ever called a resolver once and displayed a
string, with no widget to actually change a bool or pick a choice. This screen is the
part that had never been built.

Genuinely real for the settings wired in `settings_backend.SETTINGS_BACKENDS`; every
other setting in `menu_data/settings.py` still reports "not wired to a live backend yet"
through the existing `unwired_target_resolver` path — this screen is only reached for the
subset that has a real `SettingBackend` behind it.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, ListItem, ListView, Static

from services.interface.contracts import MenuItemSpec
from services.interface.tui.settings_backend import SettingBackend


class SettingValueScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, item: MenuItemSpec, backend: SettingBackend) -> None:
        super().__init__()
        self._item = item
        self._backend = backend
        self._current_value = ""
        self._known = False

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self._item.label, id="setting-title"),
            Static(self._item.tooltip, id="setting-tooltip"),
            Static("", id="setting-value"),
            ListView(id="setting-choices"),
            Button("Toggle", id="setting-toggle"),
            Static("", id="setting-status"),
            id="setting-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self._reload()

    async def _reload(self) -> None:
        self._known, self._current_value = await self._backend.get()
        value_panel = self.query_one("#setting-value", Static)
        status_panel = self.query_one("#setting-status", Static)
        toggle_button = self.query_one("#setting-toggle", Button)
        choices_list = self.query_one("#setting-choices", ListView)

        if not self._known:
            value_panel.update("Unknown — no install root could be resolved (a dev checkout has no config to read).")
            toggle_button.display = False
            await choices_list.clear()
            choices_list.display = False
            return

        value_panel.update(f"Current value: {self._current_value}")
        if self._backend.restart_required_note:
            status_panel.update(self._backend.restart_required_note)

        if self._backend.kind == "bool_ro":
            toggle_button.display = False
            choices_list.display = False
        elif self._backend.kind == "bool_rw":
            toggle_button.display = True
            choices_list.display = False
        elif self._backend.kind == "choice_rw":
            toggle_button.display = False
            choices_list.display = True
            await choices_list.clear()
            for choice in self._backend.choices:
                marker = " (current)" if choice == self._current_value else ""
                await choices_list.append(ListItem(Static(f"{choice}{marker}"), id=f"choice-{choice}"))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "setting-toggle" or self._backend.set is None:
            return
        new_value = "false" if self._current_value == "true" else "true"
        ok = await self._backend.set(new_value)
        status = self.query_one("#setting-status", Static)
        status.update(f"Saved: {new_value}" if ok else "Save failed — no install root known.")
        await self._reload()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self._backend.set is None or not event.item.id:
            return
        choice = event.item.id.removeprefix("choice-")
        ok = await self._backend.set(choice)
        status = self.query_one("#setting-status", Static)
        status.update(f"Saved: {choice}" if ok else "Save failed — no install root known.")
        await self._reload()


__all__ = ["SettingValueScreen"]

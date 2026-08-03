"""The one generic menu-data renderer (`v3-deepdive-14-interface-api.md` §3 — a binding
rule, not a preference). Any screen that is fundamentally "a list of labeled actions" is
declarative `MenuItemSpec` data rendered here; adding a menu item is an edit to data, never
new screen code. Submenus push a new `MenuScreen` onto the same stack.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, ListItem, ListView, Static

from services.interface.contracts import MenuItemSpec

#: Resolves a `MenuItemSpec.target` dotted reference to a live call. Interface API owns no
#: business logic (`docs/PRINCIPLES.md` §1's "thin renderer" rule) — this is the one seam
#: through which the real API call happens, injected rather than hardcoded so `MenuScreen`
#: itself never imports a specific Core API client.
TargetResolver = Callable[[MenuItemSpec], Awaitable[str]]


async def unwired_target_resolver(item: MenuItemSpec) -> str:
    """The honest default: reports the target isn't wired yet rather than fabricating a
    result. `docs/PRINCIPLES.md`'s own "never plausible-looking data" rule, applied to the
    TUI shell exactly as `core/agent_control/backends/local.py` already applies it to
    `CoreUnavailable`."""
    return f"{item.target} is not wired to a live backend yet."


class MenuScreen(Screen):
    """Renders one `tuple[MenuItemSpec, ...]` as a navigable list.

    `kind == "submenu"` pushes a new `MenuScreen` for the item's own children (looked up by
    `path` prefix in `submenu_source`, since `MenuItemSpec` itself carries no nested
    children — the tree is flat, grouped by dotted-path prefix, matching how
    `find_setting` already treats it).
    """

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(
        self,
        title: str,
        items: tuple[MenuItemSpec, ...],
        *,
        resolver: TargetResolver = unwired_target_resolver,
        locale: str = "en-PH",
    ) -> None:
        super().__init__()
        self._title = title
        self._items = items
        self._resolver = resolver
        self._locale = locale

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(self._title, id="menu-title"),
            ListView(*(ListItem(Static(self._label(i)), id=self._safe_id(i)) for i in self._items), id="menu-list"),
            Static("", id="menu-tooltip"),
        )
        yield Footer()

    @staticmethod
    def _safe_id(item: MenuItemSpec) -> str:
        return "item-" + item.path.replace(".", "-")

    @staticmethod
    def _label(item: MenuItemSpec) -> str:
        suffix = " >" if item.kind == "submenu" else ""
        return f"{item.label}{suffix}"

    def _item_for_id(self, widget_id: str | None) -> MenuItemSpec | None:
        if not widget_id:
            return None
        path = widget_id.removeprefix("item-").replace("-", ".")
        return next((i for i in self._items if i.path == path), None)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = self._item_for_id(event.item.id if event.item else None)
        tooltip = self.query_one("#menu-tooltip", Static)
        tooltip.update(item.tooltip if item else "")

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = self._item_for_id(event.item.id if event.item else None)
        if item is None:
            return
        if item.kind == "submenu":
            from services.interface.tui.menu_data import submenu_items

            self.app.push_screen(
                MenuScreen(item.label, submenu_items(item.path), resolver=self._resolver, locale=self._locale)
            )
            return
        result = await self._resolver(item)
        self.query_one("#menu-tooltip", Static).update(result)


__all__ = ["MenuScreen", "TargetResolver", "unwired_target_resolver"]

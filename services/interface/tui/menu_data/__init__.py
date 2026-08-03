"""Aggregates every declarative menu tree in one place so `MenuScreen` can resolve a
submenu by dotted-path prefix without importing each domain module itself.

The tree is flat (`MenuItemSpec` carries no nested-children field) and grouped by path
prefix — `submenu_items("settings")` returns every item whose path starts with
`"settings."` at exactly one level deeper, matching how `find_setting`
(`core/agent_control/backends/local.py`) already treats this same data.
"""

from __future__ import annotations

from services.interface.contracts import MenuItemSpec
from services.interface.tui.menu_data.geo_tools import GEO_TOOLS_MENU
from services.interface.tui.menu_data.root import ROOT_MENU
from services.interface.tui.menu_data.settings import SETTINGS_MENU

#: Every domain tree this build ships, concatenated. Adding a domain module is adding its
#: tuple here — never a change to `submenu_items` or `MenuScreen` itself.
ALL_MENU_ITEMS: tuple[MenuItemSpec, ...] = ROOT_MENU + SETTINGS_MENU + GEO_TOOLS_MENU


def submenu_items(parent_path: str) -> tuple[MenuItemSpec, ...]:
    """Every item one dotted-path level directly under `parent_path`.

    `"settings"` -> `settings.general`, `settings.updates`, ... as one entry each (not
    `settings.general.tenancy_mode`, which is two levels down) — a submenu screen shows
    its immediate children, and drilling into `settings.general` shows the leaves.
    """
    prefix = f"{parent_path}."
    depth = parent_path.count(".") + 2
    seen: dict[str, MenuItemSpec] = {}
    for item in ALL_MENU_ITEMS:
        if not item.path.startswith(prefix):
            continue
        segments = item.path.split(".")
        if len(segments) == depth:
            seen.setdefault(item.path, item)
        elif len(segments) > depth:
            group_path = ".".join(segments[:depth])
            if group_path not in seen:
                label = segments[depth - 1].replace("_", " ").title()
                seen[group_path] = MenuItemSpec(
                    path=group_path, label=label, tooltip=f"{label} settings.",
                    target=f"interface.open_submenu.{group_path}", kind="submenu",
                )
    return tuple(seen.values())


__all__ = ["ALL_MENU_ITEMS", "submenu_items"]

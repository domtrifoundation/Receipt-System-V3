"""`submenu_items()` — real dotted-path grouping over `ALL_MENU_ITEMS`."""

from __future__ import annotations

from services.interface.tui.menu_data import ALL_MENU_ITEMS, submenu_items
from services.interface.tui.menu_data.root import ROOT_MENU
from services.interface.tui.menu_data.settings import SETTINGS_MENU


def test_root_menu_items_are_all_top_level_paths():
    assert all("." not in i.path for i in ROOT_MENU)


def test_settings_submenu_groups_leaves_into_their_own_domains():
    groups = submenu_items("settings")
    group_paths = {g.path for g in groups}
    assert "settings.general" in group_paths
    assert "settings.updates" in group_paths
    assert all(g.kind == "submenu" for g in groups)


def test_drilling_into_a_settings_domain_returns_its_real_leaves():
    leaves = submenu_items("settings.general")
    leaf_paths = {leaf.path for leaf in leaves}
    assert "settings.general.tenancy_mode" in leaf_paths
    assert "settings.general.dev_mode" in leaf_paths


def test_submenu_items_for_an_empty_domain_returns_nothing():
    assert submenu_items("settings.nonexistent") == ()


def test_all_menu_items_includes_every_domain():
    assert set(ROOT_MENU) <= set(ALL_MENU_ITEMS)
    assert set(SETTINGS_MENU) <= set(ALL_MENU_ITEMS)

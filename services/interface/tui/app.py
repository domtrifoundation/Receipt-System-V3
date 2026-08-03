"""The TUI entrypoint (`v3-deepdive-14-interface-api.md` §7 — asyncio-native by
construction, no additional concurrency design needed beyond what Textual provides).

**Not in the deep-dive's own §2 package layout**, same justification pattern already used
for `supervisor/single_instance.py` and `supervisor/version_pins.py` this session: the
layout names the pieces (`menu_screen.py`, `custom_screens/`, `theme.py`, `i18n.py`) but
never the actual `App` subclass wiring them together — every other Core API's real
implementation this session added the equivalent file (`service.py`, `service.py`) without
being separately named in its own layout either.

**Boot ownership, stated precisely rather than assumed**: a normal TUI launch does not
re-run the fleet boot — Supervisor already booted Layer 1 before the TUI itself is even
launched (`docs/PROCESS_TOPOLOGY.md`). `boot_specs` is `None` on that path, and the app
goes straight to the root menu. It is non-`None` only for the TUI's own single-instance
restart (§3.3's fullscreen-takeover case) or a dev/test harness that wants to exercise the
boot screen directly — the same seam, used honestly for both real cases it actually has.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from services.interface.tui.custom_screens.boot_sequence import BootSequenceScreen
from services.interface.tui.custom_screens.credits import CreditsScreen
from services.interface.tui.i18n import DEFAULT_LOCALE, t
from services.interface.tui.menu_data import ALL_MENU_ITEMS, submenu_items
from services.interface.tui.menu_screen import MenuScreen, TargetResolver, unwired_target_resolver
from supervisor.contracts import BootReport, ServiceSpec

#: `MenuItemSpec.target` values the root menu uses to name a custom screen rather than a
#: real API call — see `menu_data/root.py`'s own docstring for why this convention exists.
_BUILT_CUSTOM_SCREENS = {"interface.open_screen.credits": lambda locale: CreditsScreen()}


class InterfaceApp(App):
    """The one Textual `App` this package ships. `boot_specs`/`clone_dir`/`channel` are
    only supplied when this launch needs to run (or re-run) the real fleet boot; see the
    module docstring for the two real cases that applies to."""

    TITLE = "DOMTRI / Resibo"

    def __init__(
        self,
        *,
        boot_specs: tuple[ServiceSpec, ...] | None = None,
        clone_dir: Path | None = None,
        channel: str = "dev",
        locale: str = DEFAULT_LOCALE,
        resolver: TargetResolver = unwired_target_resolver,
    ) -> None:
        super().__init__()
        self._boot_specs = boot_specs
        self._clone_dir = clone_dir
        self._channel = channel
        self._locale = locale
        self._resolver = self._wrap_resolver(resolver)

    def _wrap_resolver(self, base: TargetResolver) -> TargetResolver:
        """Intercepts `interface.open_screen.*`/`interface.open_submenu.*` targets to push
        a real screen; everything else defers to `base` (a live API call, once a caller
        supplies one, or the honest `unwired_target_resolver` default)."""

        async def resolver(item):
            if item.target.startswith("interface.open_submenu."):
                path = item.target.removeprefix("interface.open_submenu.")
                self.push_screen(MenuScreen(item.label, submenu_items(path), resolver=self._resolver, locale=self._locale))
                return ""
            if item.target in _BUILT_CUSTOM_SCREENS:
                self.push_screen(_BUILT_CUSTOM_SCREENS[item.target](self._locale))
                return ""
            if item.target.startswith("interface.open_screen."):
                return f"{item.label} isn't built yet — tracked in services/interface/CLAUDE.md."
            return await base(item)

        return resolver

    def on_mount(self) -> None:
        if self._boot_specs and self._clone_dir:
            self.push_screen(
                BootSequenceScreen(
                    self._boot_specs, self._clone_dir, self._channel,
                    on_complete=self._after_boot, locale=self._locale,
                )
            )
        else:
            self._push_root_menu()

    async def _after_boot(self, report: BootReport) -> None:
        self.pop_screen()
        if report.ok:
            self._push_root_menu()
        else:
            failed = ", ".join(report.failed_services)
            self.push_screen(MenuScreen(f"Boot failed: {failed}", (), resolver=self._resolver, locale=self._locale))

    def _push_root_menu(self) -> None:
        root_items = tuple(i for i in ALL_MENU_ITEMS if "." not in i.path)
        self.push_screen(MenuScreen(t("app.title", self._locale), root_items, resolver=self._resolver, locale=self._locale))


__all__ = ["InterfaceApp"]

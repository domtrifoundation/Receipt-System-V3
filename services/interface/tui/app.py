"""The TUI entrypoint (`v3-deepdive-14-interface-api.md` §7 — asyncio-native by
construction, no additional concurrency design needed beyond what Textual provides).

**Not in the deep-dive's own §2 package layout**, same justification pattern already used
for `supervisor/single_instance.py` and `supervisor/version_pins.py` this session: the
layout names the pieces (`menu_screen.py`, `custom_screens/`, `theme.py`, `i18n.py`) but
never the actual `App` subclass wiring them together — every other Core API's real
implementation this session added the equivalent file (`service.py`, `service.py`) without
being separately named in its own layout either.

**Boot ownership — a genuinely detachable display client of Supervisor, corrected twice
this session before landing here.** Interface API's own §1 boundary is explicit: this
package is a *display* client, never the process that starts things. `supervisor_address`
is what this app connects to — `BootSequenceScreen` streams real progress from
Supervisor's own `StreamBootProgress` RPC (Supervisor is the one that actually calls
`boot_many()`); this app never spawns a single service itself.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from services.interface.tui.banners import header_line
from services.interface.tui.custom_screens.boot_sequence import BootSequenceScreen
from services.interface.tui.custom_screens.credits import CreditsScreen
from services.interface.tui.custom_screens.fleet_screen import FleetScreen
from services.interface.tui.i18n import DEFAULT_LOCALE, t
from services.interface.tui.menu_data import ALL_MENU_ITEMS, submenu_items
from services.interface.tui.menu_screen import MenuScreen, TargetResolver, unwired_target_resolver
from supervisor.contracts import BootReport

#: The real, current fleet size (`supervisor/fleet.py`'s own discovery) — a display
#: estimate for the progress bar's own total, not authoritative; `BootSequenceScreen`
#: never needs an exact count to function correctly, only something reasonable to show
#: progress against before the first real result arrives.
ESTIMATED_FLEET_SIZE = 31

#: `MenuItemSpec.target` values the root menu uses to name a custom screen rather than a
#: real API call — see `menu_data/root.py`'s own docstring for why this convention exists.
_BUILT_CUSTOM_SCREENS = {"interface.open_screen.credits": lambda locale: CreditsScreen()}


class InterfaceApp(App):
    """The one Textual `App` this package ships. `supervisor_address` is only supplied
    when this launch needs to show the real boot (the normal `start.bat` path, or the
    TUI's own single-instance restart, §3.3); otherwise the app goes straight to the
    root menu, assuming a fleet is already up and reachable."""

    TITLE = "DOMTRI / Resibo"

    def __init__(
        self,
        *,
        supervisor_address: str | None = None,
        channel: str = "local",
        locale: str = DEFAULT_LOCALE,
        resolver: TargetResolver = unwired_target_resolver,
    ) -> None:
        super().__init__()
        self._supervisor_address = supervisor_address
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
            if item.target == "interface.open_screen.fleet_updates":
                self.push_screen(FleetScreen(self._supervisor_address, self._channel, locale=self._locale))
                return ""
            if item.target in _BUILT_CUSTOM_SCREENS:
                self.push_screen(_BUILT_CUSTOM_SCREENS[item.target](self._locale))
                return ""
            if item.target.startswith("interface.open_screen."):
                return f"{item.label} isn't built yet — tracked in services/interface/CLAUDE.md."
            return await base(item)

        return resolver

    def on_mount(self) -> None:
        if self._supervisor_address:
            self.push_screen(
                BootSequenceScreen(
                    self._supervisor_address, self._channel, ESTIMATED_FLEET_SIZE,
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
        # The persistent codename header (`v3-plan-02-architecture.md`'s own "(b)
        # persistently at the top of the TUI's main menu navigation, smaller/header-style"
        # placement) — small, one line, distinct from the Boot Sequence screen's own full
        # ASCII banner.
        root_items = tuple(i for i in ALL_MENU_ITEMS if "." not in i.path)
        title = f"{header_line()} — {t('app.title', self._locale)}"
        self.push_screen(MenuScreen(title, root_items, resolver=self._resolver, locale=self._locale))


__all__ = ["ESTIMATED_FLEET_SIZE", "InterfaceApp"]


def _parse_args(argv: list[str]) -> dict:
    """`--supervisor <address> --channel <channel>` — real CLI args, not positional, since
    this is meant to be invoked by `supervisor/__main__.py` itself and reads better as a
    named contract at that call site than two bare positional strings would."""
    kwargs: dict = {}
    i = 0
    while i < len(argv):
        if argv[i] == "--supervisor" and i + 1 < len(argv):
            kwargs["supervisor_address"] = argv[i + 1]
            i += 2
        elif argv[i] == "--channel" and i + 1 < len(argv):
            kwargs["channel"] = argv[i + 1]
            i += 2
        else:
            i += 1
    return kwargs


if __name__ == "__main__":  # pragma: no cover
    # The real thing start.bat/start.sh hands off to, via supervisor/__main__.py.
    #
    #   python -m services.interface.tui.app
    #       -- straight to the root menu, assumes a fleet is already up and reachable
    #       (dev/test harness, or a future re-attach flow).
    #   python -m services.interface.tui.app --supervisor <address> --channel <channel>
    #       -- the real start.bat path: streams the real boot from Supervisor's own
    #       StreamBootProgress RPC, live, through this app's BootSequenceScreen.
    import sys

    InterfaceApp(**_parse_args(sys.argv[1:])).run()

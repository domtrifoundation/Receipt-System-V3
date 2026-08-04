"""The TUI entrypoint (`v3-deepdive-14-interface-api.md` §7 — asyncio-native by
construction, no additional concurrency design needed beyond what Textual provides).

**Not in the deep-dive's own §2 package layout**, same justification pattern already used
for `supervisor/single_instance.py` and `supervisor/version_pins.py` this session: the
layout names the pieces (`menu_screen.py`, `custom_screens/`, `theme.py`, `i18n.py`) but
never the actual `App` subclass wiring them together — every other Core API's real
implementation this session added the equivalent file (`service.py`, `service.py`) without
being separately named in its own layout either.

**Boot ownership — the TUI drives its own boot screen, corrected from an earlier wrong
turn this same session.** `supervisor/__main__.py` originally booted the fleet headlessly
(raw `print()` progress) and only launched the TUI *after* — backwards from the deep-
dive's own "only once every service is confirmed healthy does Interface API's loading
screen hand off to the running TUI," which describes the loading screen as belonging to
the TUI itself. Fixed: `supervisor/__main__.py` now launches this app immediately with
`boot_specs`/`clone_dir`/`install_root` set, and `BootSequenceScreen` (this app's own,
already-built loading screen) is what the operator actually watches boot happen — real
per-service progress, the BETA banner, all of it — with `boot_many()` running underneath
it, not before it. `install_root` is what lets `_on_service_result` write Supervisor's
own dynamic-address registry and track spawned PIDs for cleanup, since the boot itself
happens in this process now, not Supervisor's.
"""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import App

from services.interface.tui.banners import header_line
from services.interface.tui.custom_screens.boot_sequence import BootSequenceScreen
from services.interface.tui.custom_screens.credits import CreditsScreen
from services.interface.tui.i18n import DEFAULT_LOCALE, t
from services.interface.tui.menu_data import ALL_MENU_ITEMS, submenu_items
from services.interface.tui.menu_screen import MenuScreen, TargetResolver, unwired_target_resolver
from supervisor.contracts import BootReport, ServiceLaunchResult, ServiceSpec

SERVICE_ADDRESSES_RELPATH = Path("supervisor") / "service_addresses.json"

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
        install_root: Path | None = None,
        locale: str = DEFAULT_LOCALE,
        resolver: TargetResolver = unwired_target_resolver,
    ) -> None:
        super().__init__()
        self._boot_specs = boot_specs
        self._clone_dir = clone_dir
        self._channel = channel
        self._install_root = install_root
        self._locale = locale
        self._resolver = self._wrap_resolver(resolver)
        #: Every service this run actually spawned, for real cleanup on exit — the same
        #: orphan-prevention `supervisor/__main__.py` used to own when it was the one
        #: calling `boot_many()`; now that the boot happens here, so does the tracking.
        self.spawned_pids: list[int] = []
        self._service_addresses: dict[str, str] = {}

    def _on_service_result(self, result: ServiceLaunchResult) -> None:
        if result.pid is not None:
            self.spawned_pids.append(result.pid)
        if result.address and self._install_root is not None:
            self._service_addresses[result.name] = result.address
            target = self._install_root / SERVICE_ADDRESSES_RELPATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(self._service_addresses, indent=2) + "\n", encoding="utf-8")

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
                    on_service_result=self._on_service_result,
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


__all__ = ["InterfaceApp"]


if __name__ == "__main__":  # pragma: no cover
    # The real, previously-missing thing start.bat/start.sh hands off to. Supervisor's
    # own __main__ (headless — no textual dependency in its own grpc-only venv) launches
    # this as a subprocess, using the active clone's own services.interface venv.
    #
    # Two shapes, both real:
    #   python -m services.interface.tui.app                        -- straight to menu,
    #       assumes the fleet is already up (dev/test harness, or a future re-attach flow).
    #   python -m services.interface.tui.app <clone_dir> <channel> <install_root>
    #       -- the real start.bat path: builds the fleet registry from clone_dir and boots
    #       it live, on screen, through this app's own BootSequenceScreen — matching the
    #       deep-dive's own "only once every service is confirmed healthy does Interface
    #       API's loading screen hand off to the running TUI." services.interface's own
    #       venv already has both textual and grpc (common/requirements.txt's own base),
    #       so this process can run boot_many() directly; it does not need Supervisor to
    #       have done it first.
    import os
    import signal
    import sys

    app_kwargs = {}
    if len(sys.argv) > 1:
        from supervisor.fleet import build_fleet_specs

        clone_dir = Path(sys.argv[1])
        channel = sys.argv[2] if len(sys.argv) > 2 else "local"
        install_root = Path(sys.argv[3]) if len(sys.argv) > 3 else None
        app_kwargs = {
            "boot_specs": build_fleet_specs(clone_dir),
            "clone_dir": clone_dir,
            "channel": channel,
            "install_root": install_root,
        }

    app = InterfaceApp(**app_kwargs)
    try:
        app.run()
    finally:
        for pid in app.spawned_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

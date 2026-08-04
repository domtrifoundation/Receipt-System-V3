"""`find_setting` (`v3-deepdive-14-interface-api.md` §3.1, V2's `find_setting` carried
forward) — on the enumerated custom-screen exception list, previously a placeholder
reporting "not built yet."

**Reuses `core/agent_control/backends/local.py`'s real `LocalCoreBackend.find_setting()`
in-process, deliberately not through Agent Control's `ExecuteAgentAction` RPC.** That RPC
is gated by an agent token (`core/agent_control/CLAUDE.md`'s own "an agent is never more
capable than the human who authorized it") — real machinery for an external AI agent, not
the right shape for the human operator sitting at this TUI. The matcher itself has no
side effects and no state beyond Interface API's own `SETTINGS_MENU` — it fuzzy-matches
Interface's own declarative menu data against itself, which is presentation logic over
this package's own data, not a call into another API's business logic. The same class of
exception the wizard screen's own docstring already documents for a different reason
(no service process exists yet at that point in the lifecycle); here the reason is
narrower — the "service" this would otherwise call is gated for an audience this call
site isn't.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, ListItem, ListView, Static

from services.interface.contracts import MenuItemSpec
from services.interface.tui.i18n import t
from services.interface.tui.menu_screen import TargetResolver, unwired_target_resolver


class FindSettingScreen(Screen):
    """Live fuzzy search as the operator types, `MenuScreen`'s own selection/navigation
    behaviour reused for the results list — selecting a match resolves it through the
    same `TargetResolver` seam every other screen already uses, so a matched setting or
    submenu opens exactly as if it had been reached by browsing."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, *, resolver: TargetResolver = unwired_target_resolver, locale: str = "en-PH") -> None:
        super().__init__()
        self._resolver = resolver
        self._locale = locale
        self._matches: dict[str, dict] = {}

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(t("find_setting.title", self._locale), id="find-title"),
            Input(placeholder=t("find_setting.placeholder", self._locale), id="find-query"),
            ListView(id="find-results"),
            Static("", id="find-detail"),
            id="find-container",
        )
        yield Footer()

    async def on_input_changed(self, event: Input.Changed) -> None:
        await self._run_search(event.value)

    async def _run_search(self, query: str) -> None:
        from core.agent_control.backends.local import LocalCoreBackend

        result = LocalCoreBackend().find_setting(query)
        self._matches = {m["path"]: m for m in result["matches"]}

        list_view = self.query_one("#find-results", ListView)
        await list_view.clear()
        for match in result["matches"]:
            label = f"{match['label']} ({match['score']:.0f}%)"
            await list_view.append(ListItem(Static(label), id=self._safe_id(match["path"])))

        detail = self.query_one("#find-detail", Static)
        if query.strip() and not result["matches"]:
            detail.update(t("find_setting.no_matches", self._locale, query=query))
        else:
            detail.update("")

    @staticmethod
    def _safe_id(path: str) -> str:
        return "find-" + path.replace(".", "-")

    def _match_for_id(self, widget_id: str | None) -> dict | None:
        if not widget_id:
            return None
        path = widget_id.removeprefix("find-").replace("-", ".")
        return self._matches.get(path)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        match = self._match_for_id(event.item.id if event.item else None)
        self.query_one("#find-detail", Static).update(match["tooltip"] if match else "")

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        match = self._match_for_id(event.item.id if event.item else None)
        if match is None:
            return
        item = MenuItemSpec(
            path=match["path"], label=match["label"], tooltip=match["tooltip"],
            target=match["target"], kind=match["kind"], docs_ref=match["docs_ref"],
        )
        result = await self._resolver(item)
        self.query_one("#find-detail", Static).update(result)


__all__ = ["FindSettingScreen"]

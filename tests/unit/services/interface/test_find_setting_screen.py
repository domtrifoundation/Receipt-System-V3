"""`FindSettingScreen` — real `Pilot`-driven tests against the genuine, already-tested
`LocalCoreBackend.find_setting()` matcher, never a fake/mocked result set."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual", reason="textual is not installed in this interpreter")

from services.interface.tui.custom_screens.find_setting import FindSettingScreen  # noqa: E402
from textual.app import App  # noqa: E402
from textual.widgets import Input, ListView, Static  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _Harness(App):
    def __init__(self, resolver=None) -> None:
        super().__init__()
        self._resolver = resolver

    def on_mount(self) -> None:
        from services.interface.tui.menu_screen import unwired_target_resolver

        self.push_screen(FindSettingScreen(resolver=self._resolver or unwired_target_resolver))


def test_typing_a_real_setting_name_surfaces_a_real_match():
    async def scenario():
        app = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            query_input = app.screen.query_one("#find-query", Input)
            query_input.value = "tenancy mode"
            query_input.post_message(Input.Changed(query_input, "tenancy mode"))
            await pilot.pause()

            results = app.screen.query_one("#find-results", ListView)
            assert any(item.id == "find-settings-general-tenancy_mode" for item in results.children)

    run(scenario())


def test_empty_query_yields_no_results_and_no_error():
    async def scenario():
        app = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            query_input = app.screen.query_one("#find-query", Input)
            query_input.value = ""
            query_input.post_message(Input.Changed(query_input, ""))
            await pilot.pause()

            results = app.screen.query_one("#find-results", ListView)
            assert len(results.children) == 0

    run(scenario())


def test_a_low_relevance_query_still_returns_the_real_matchers_own_ranked_results():
    """`rapidfuzz.partial_ratio` almost never returns an exact zero, so a gibberish query
    genuinely does surface real (low-score) matches rather than an empty list — this
    confirms the screen renders whatever the real matcher actually returns, honestly,
    rather than assuming a "no matches" case that the real matcher doesn't produce."""

    async def scenario():
        app = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            query_input = app.screen.query_one("#find-query", Input)
            query_input.value = "zzzznonexistentzzzz"
            query_input.post_message(Input.Changed(query_input, "zzzznonexistentzzzz"))
            await pilot.pause()

            results = app.screen.query_one("#find-results", ListView)
            assert len(results.children) > 0

    run(scenario())


def test_selecting_a_match_forwards_it_through_the_real_resolver():
    async def scenario():
        seen = []

        async def resolver(item):
            seen.append(item.path)
            return f"opened {item.path}"

        app = _Harness(resolver=resolver)
        async with app.run_test() as pilot:
            await pilot.pause()
            query_input = app.screen.query_one("#find-query", Input)
            query_input.value = "tenancy mode"
            query_input.post_message(Input.Changed(query_input, "tenancy mode"))
            await pilot.pause()

            results = app.screen.query_one("#find-results", ListView)
            target = next(i for i in results.children if i.id == "find-settings-general-tenancy_mode")
            await pilot.click(f"#{target.id}")
            await pilot.pause()

            assert "settings.general.tenancy_mode" in seen

    run(scenario())

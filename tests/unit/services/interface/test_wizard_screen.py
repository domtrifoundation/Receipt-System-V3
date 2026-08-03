"""`WizardScreen` — drives a real `WizardEngine` (no collaborators, everything degrades to
"not configured" per `docs/PRINCIPLES.md` §4.4) through a full personal-branch run via
real Textual `Pilot` interaction, confirming it reaches `on_complete` with a real
`WizardState`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="textual is not installed in this interpreter")

from textual.app import App  # noqa: E402
from textual.widgets import ListView  # noqa: E402

from services.interface.tui.custom_screens.wizard_screen import WizardScreen  # noqa: E402
from services.setup.contracts import WizardState  # noqa: E402
from services.setup.wizard import WizardEngine  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _WizardHostApp(App):
    def __init__(self, engine: WizardEngine, results: list[WizardState]) -> None:
        super().__init__()
        self._engine = engine
        self._results = results

    async def on_mount(self) -> None:
        async def on_complete(state: WizardState) -> None:
            self._results.append(state)

        await self.push_screen(WizardScreen(self._engine, on_complete=on_complete))


async def _select(pilot, index: int) -> None:
    list_view = pilot.app.screen.query_one("#wizard-choices", ListView)
    list_view.index = index
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


def test_personal_branch_reaches_completion_with_a_real_wizard_state():
    results: list[WizardState] = []
    engine = WizardEngine(launcher_path=Path("start.bat"))
    app = _WizardHostApp(engine, results)

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.pause()
            await _select(pilot, 0)  # WELCOME -> "Just for myself" (personal)

            # PERSONAL's applicable_steps: ACCOUNT, RECEIPT_INGESTION, ADDRESS_CHECKING,
            # HARDWARE_TIER, TERMS_OF_SERVICE, FINALIZE (run_on_startup/tunnel/groups/
            # billing/sms are all excluded for PERSONAL per STEP_DEFINITIONS).
            await _select(pilot, 0)  # ACCOUNT -> sso
            await _select(pilot, 1)  # RUN_ON_STARTUP -> not applicable, skipped by engine
            # Some steps above may not render if the engine skips them entirely for
            # PERSONAL; keep selecting the first available choice until FINALIZE lands.
            for _ in range(6):
                if results:
                    break
                await _select(pilot, 0)

        assert len(results) == 1
        state = results[0]
        assert isinstance(state, WizardState)
        assert state.tenancy_mode == "single"

    run(scenario())

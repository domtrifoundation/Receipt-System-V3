"""The first-run interactive setup wizard TUI screen (`v3-deepdive-11-setup-api.md` §7 —
"TUI-driven via the same menu-data pattern as the rest of Interface API rather than a
separate wizard UI technology"). Drives `services/setup/wizard.py`'s own `WizardEngine.run()`
directly, in-process — not over gRPC — because the wizard genuinely runs *before* Supervisor
boots the fleet (§7.4: wizard steps complete, then `strip_development_content()`, then
`build_webapp()`, then Supervisor's Boot Sequence), so no Setup API *service process* is
up yet to be a gRPC server for it. The engine's own async-generator shape
(`gen.asend(answer)`) maps onto this screen's own answer-then-next-prompt loop exactly the
way its own docstring says it maps onto bidirectional gRPC streaming — same shape, direct
in-process call instead of a wire call, for the one moment in the whole system's lifecycle
where there is no running service to call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, ListItem, ListView, Static

from common.frozen_dict import FrozenDict
from services.interface.tui.banners import ascii_banner
from services.interface.tui.custom_screens.wizard_script import WIZARD_SCRIPT, WizardChoice
from services.setup.contracts import WizardAnswer, WizardState
from services.setup.wizard import WizardEngine

OnWizardComplete = Callable[[WizardState], Awaitable[None]]


class WizardScreen(Screen):
    """Steps through `engine.run()` one prompt at a time. `on_complete(state)` is called
    once the generator is exhausted, with `engine.build_final_state()`'s own result."""

    def __init__(self, engine: WizardEngine, *, on_complete: OnWizardComplete) -> None:
        super().__init__()
        self._engine = engine
        self._on_complete = on_complete
        self._gen = None
        self._current_choices: tuple[WizardChoice, ...] = ()
        self._current_step_id_value = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(ascii_banner(), id="wizard-banner"),
            Static("", id="wizard-title"),
            Static("", id="wizard-body"),
            ListView(id="wizard-choices"),
            Static("", id="wizard-note"),
            id="wizard-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        self._gen = self._engine.run()
        prompt = await anext(self._gen)
        await self._render_prompt(prompt.step_id)

    async def _render_prompt(self, step_id) -> None:
        script = WIZARD_SCRIPT.get(step_id)
        if script is None:
            await self._advance(WizardAnswer(step_id=step_id, skipped=True))
            return

        self.query_one("#wizard-title", Static).update(script.title)
        self.query_one("#wizard-body", Static).update(script.body)
        self.query_one("#wizard-note", Static).update("")
        self._current_choices = script.choices
        self._current_step_id_value = step_id

        choices_list = self.query_one("#wizard-choices", ListView)
        await choices_list.clear()
        for index, choice in enumerate(script.choices):
            await choices_list.append(ListItem(Static(choice.label), id=f"choice-{index}"))

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not event.item or not event.item.id:
            return
        index = int(event.item.id.removeprefix("choice-"))
        choice = self._current_choices[index]

        if choice.needs_followup:
            self.query_one("#wizard-note", Static).update(
                "This part of setup isn't available inline yet — skipping for now. "
                "You can configure it later in Settings."
            )

        answer = WizardAnswer(
            step_id=self._current_step_id_value,
            skipped=choice.skipped or choice.needs_followup,
            data=FrozenDict(choice.answer_data if not choice.needs_followup else {}),
        )
        await self._advance(answer)

    async def _advance(self, answer: WizardAnswer) -> None:
        try:
            prompt = await self._gen.asend(answer)
        except StopAsyncIteration:
            state = self._engine.build_final_state()
            await self._on_complete(state)
            return
        await self._render_prompt(prompt.step_id)


__all__ = ["WizardScreen"]

"""The Boot Sequence loading screen (`v3-deepdive-14-interface-api.md` §3.2, §3.3) — on
the enumerated custom-screen exception list. Real, live progress: `boot_many()`'s own
`on_result` callback (`supervisor/boot_sequence.py`) is what drives this screen's own
progress list, not a fabricated animation timed independently of the real launches.

Also reused, unchanged, for the TUI's own single-instance restart (§3.3's own stated
asymmetry — the TUI's restart is fullscreen because it necessarily takes over the same
terminal the operator is looking at) via `skip_animation`, a clearly-secondary control.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, ProgressBar, Static

from services.interface.tui.banners import ascii_banner
from services.interface.tui.i18n import t
from supervisor.boot_sequence import boot_many
from supervisor.contracts import BootReport, ServiceLaunchResult, ServiceSpec

OnBootComplete = Callable[[BootReport], Awaitable[None]]


class BootSequenceScreen(Screen):
    """Launches `specs` in dependency order via the real `boot_many()`, showing each
    service's own result as it happens. Calls `on_complete(report)` when done — the caller
    (`app.py`) decides what to do with a failed boot; this screen only renders progress.
    """

    BINDINGS = [("s", "toggle_skip", "Skip animation")]

    def __init__(
        self, specs: tuple[ServiceSpec, ...], clone_dir: Path, channel: str,
        *, on_complete: OnBootComplete, locale: str = "en-PH",
        on_service_result: Callable[[ServiceLaunchResult], None] | None = None,
    ) -> None:
        super().__init__()
        self._specs = specs
        self._clone_dir = clone_dir
        self._channel = channel
        self._on_complete = on_complete
        self._locale = locale
        self._skip_animation = False
        #: Real, per-service side effects the caller needs as results come in — PID
        #: tracking for cleanup, writing Supervisor's own dynamic-address registry
        #: (`supervisor/__main__.py`'s previous job, now this screen's since the boot
        #: itself moved here — see `app.py`'s own docstring for why).
        self._on_service_result = on_service_result

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(ascii_banner(), id="boot-banner"),
            Static(t("boot.title", self._locale), id="boot-title"),
            ProgressBar(total=max(len(self._specs), 1), id="boot-progress"),
            Static("", id="boot-log"),
            Button(t("boot.skip_animation", self._locale), id="boot-skip"),
            id="boot-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.run_worker(self._boot(), exclusive=True)

    def action_toggle_skip(self) -> None:
        self._skip_animation = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "boot-skip":
            self._skip_animation = True

    async def _boot(self) -> None:
        log = self.query_one("#boot-log", Static)
        progress = self.query_one("#boot-progress", ProgressBar)
        lines: list[str] = []

        def on_result(result: ServiceLaunchResult) -> None:
            key = "boot.stage.healthy" if result.ok else "boot.stage.failed"
            lines.append(t(key, self._locale, service=result.name, detail=result.error_detail or ""))
            log.update("\n".join(lines))
            progress.advance(1)
            if self._on_service_result is not None:
                self._on_service_result(result)

        report = await boot_many(self._specs, self._clone_dir, channel=self._channel, on_result=on_result)
        if report.ok:
            lines.append(t("boot.complete", self._locale))
            log.update("\n".join(lines))
        await self._on_complete(report)


__all__ = ["BootSequenceScreen"]

"""The TUI/Inference single-instance restart screen (§5.4/§5.3's own closed two-service
list) — fullscreen because it necessarily takes over the same terminal the operator is
looking at (`interface_tui` restarting itself mid-session, or `inference` restarting
under the operator's own eyes). A thin streaming client of Supervisor's own
`RestartServiceOnVersion` RPC, same posture as `BootSequenceScreen`'s own relationship to
`StreamBootProgress` — this screen never calls `restart_service_on_version()` itself,
Supervisor does the actual stop/launch/health-gate.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, ProgressBar, Static

from services.interface.tui.banners import ascii_banner
from services.interface.tui.i18n import t

#: Called once the stream reaches a terminal stage — `(ok, error_detail)`. `error_detail`
#: is empty on success.
OnRestartComplete = Callable[[bool, str], Awaitable[None]]

#: §5.4's own exact stage order — used only as a display total for the progress bar; the
#: real stage sequence comes from the stream itself, this is never used to gate anything.
_STAGE_COUNT = 5


class RestartScreen(Screen):
    """Streams `RestartServiceOnVersion(service_name, target_version)` and renders each
    real stage as it arrives. `service_name` is expected to already be one of
    `available_versions.SINGLE_INSTANCE_SERVICES` — Supervisor's own RPC refuses anything
    else, and that refusal renders here exactly like any other failed stage."""

    BINDINGS = [("s", "toggle_skip", "Skip animation")]

    def __init__(
        self, supervisor_address: str, service_name: str, target_version: str,
        *, on_complete: OnRestartComplete, locale: str = "en-PH",
    ) -> None:
        super().__init__()
        self._supervisor_address = supervisor_address
        self._service_name = service_name
        self._target_version = target_version
        self._on_complete = on_complete
        self._locale = locale
        self._skip_animation = False

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(ascii_banner(), id="restart-banner"),
            Static(t("restart.title", self._locale, service=self._service_name, version=self._target_version), id="restart-title"),
            ProgressBar(total=_STAGE_COUNT, id="restart-progress"),
            Static("", id="restart-log"),
            Button(t("boot.skip_animation", self._locale), id="restart-skip"),
            id="restart-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.run_worker(self._stream_restart(), exclusive=True)

    def action_toggle_skip(self) -> None:
        self._skip_animation = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "restart-skip":
            self._skip_animation = True

    async def _stream_restart(self) -> None:
        import grpc

        from supervisor.generated import supervisor_pb2 as pb
        from supervisor.generated import supervisor_pb2_grpc as pb_grpc

        log = self.query_one("#restart-log", Static)
        progress = self.query_one("#restart-progress", ProgressBar)
        lines: list[str] = []
        ok = False
        error_detail = ""

        async with grpc.aio.insecure_channel(self._supervisor_address) as channel:
            stub = pb_grpc.SupervisorServiceStub(channel)
            request = pb.RestartRequest(service_name=self._service_name, target_version=self._target_version)
            async for stage in stub.RestartServiceOnVersion(request):
                lines.append(t(f"restart.stage.{stage.stage}", self._locale, detail=stage.error_detail or ""))
                log.update("\n".join(lines))
                progress.advance(1)
                if stage.stage == "complete":
                    ok = True
                elif stage.stage == "failed":
                    error_detail = stage.error_detail

        await self._on_complete(ok, error_detail)


__all__ = ["RestartScreen"]

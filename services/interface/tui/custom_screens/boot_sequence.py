"""The Boot Sequence loading screen (`v3-deepdive-14-interface-api.md` §3.2, §3.3) — on
the enumerated custom-screen exception list.

**A real, previously-live-found ownership inversion, corrected here.** This screen used
to call `boot_many()` itself — but Supervisor is the thing that actually starts
processes; Interface API is a genuinely detachable *display* client
(`v3-deepdive-14-interface-api.md` §1's own boundary), never the process doing the
starting. This screen is now a thin streaming client of Supervisor's own
`StreamBootProgress` RPC (`supervisor.proto`) — Supervisor calls `boot_many()`, this
screen only renders whatever real progress arrives over the wire.

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
from supervisor.contracts import BootReport, ServiceLaunchResult

OnBootComplete = Callable[[BootReport], Awaitable[None]]


class BootSequenceScreen(Screen):
    """Connects to Supervisor's own `StreamBootProgress` RPC and renders each service's
    real result as it arrives. Calls `on_complete(report)` once Supervisor reports the
    boot finished — the caller (`app.py`) decides what to do with a failed boot; this
    screen only renders progress and never starts anything itself.
    """

    BINDINGS = [("s", "toggle_skip", "Skip animation")]

    def __init__(
        self, supervisor_address: str, channel: str, expected_service_count: int,
        *, on_complete: OnBootComplete, locale: str = "en-PH",
        on_service_result: Callable[[ServiceLaunchResult], None] | None = None,
    ) -> None:
        super().__init__()
        self._supervisor_address = supervisor_address
        self._channel = channel
        self._expected_service_count = expected_service_count
        self._on_complete = on_complete
        self._locale = locale
        self._skip_animation = False
        #: Real, per-service side effects the caller needs as results stream in — PID
        #: tracking for cleanup, mirroring the real addresses Supervisor already wrote to
        #: its own registry (this screen doesn't need to write them again; Supervisor,
        #: the process that actually spawned each service, already owns that file).
        self._on_service_result = on_service_result

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(ascii_banner(), id="boot-banner"),
            Static(t("boot.title", self._locale), id="boot-title"),
            ProgressBar(total=max(self._expected_service_count, 1), id="boot-progress"),
            Static("", id="boot-log"),
            Button(t("boot.skip_animation", self._locale), id="boot-skip"),
            id="boot-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.run_worker(self._stream_boot(), exclusive=True)

    def action_toggle_skip(self) -> None:
        self._skip_animation = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "boot-skip":
            self._skip_animation = True

    async def _stream_boot(self) -> None:
        import grpc

        from supervisor.generated import supervisor_pb2 as pb
        from supervisor.generated import supervisor_pb2_grpc as pb_grpc

        log = self.query_one("#boot-log", Static)
        progress = self.query_one("#boot-progress", ProgressBar)
        lines: list[str] = []
        results: list[ServiceLaunchResult] = []

        async with grpc.aio.insecure_channel(self._supervisor_address) as channel:
            stub = pb_grpc.SupervisorServiceStub(channel)
            report = BootReport(channel=self._channel, release_dir=Path("."), services=())
            async for update in stub.StreamBootProgress(pb.BootProgressRequest(channel=self._channel)):
                if update.boot_complete:
                    report = BootReport(
                        channel=self._channel, release_dir=Path("."), services=tuple(results),
                    )
                    if update.boot_ok:
                        lines.append(t("boot.complete", self._locale))
                        log.update("\n".join(lines))
                    break

                result = ServiceLaunchResult(
                    name=update.service_name, ok=update.ok,
                    pid=update.pid or None, address=update.address,
                    error_detail=update.error_detail,
                )
                results.append(result)
                key = "boot.stage.healthy" if result.ok else "boot.stage.failed"
                lines.append(t(key, self._locale, service=result.name, detail=result.error_detail or ""))
                log.update("\n".join(lines))
                progress.advance(1)
                if self._on_service_result is not None:
                    self._on_service_result(result)

        await self._on_complete(report)


__all__ = ["BootSequenceScreen"]

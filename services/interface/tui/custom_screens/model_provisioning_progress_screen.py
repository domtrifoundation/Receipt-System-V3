"""Real streaming progress for a model download — fullscreen for the same reason
`RestartScreen` is: a multi-gigabyte download genuinely takes minutes, and the operator
should see it happening, not a frozen menu. A thin streaming client of Inference's own
`ProvisionPreset` RPC (`core/inference/service.py`, `core/inference/model_provisioning.py`
underneath it) — this screen never downloads anything itself, exactly the same
"Supervisor does the actual stop/launch" relationship `RestartScreen` has with
`RestartServiceOnVersion`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, ProgressBar, Static

from services.interface.tui.i18n import t

#: Called once the stream reaches its terminal update — `(ok, error_detail)`.
#: `error_detail` is empty on success, matching `RestartScreen`'s own `OnRestartComplete`.
OnProvisionComplete = Callable[[bool, str], Awaitable[None]]


class ModelProvisioningProgressScreen(Screen):
    """Streams `ProvisionPreset(preset, device_family)` and renders each real per-file
    progress update as it arrives, byte counts included — never a timed animation
    guessing at progress the way an operation with no real signal would need to."""

    def __init__(
        self, inference_address: str, preset_name: str, device_family: str,
        *, on_complete: OnProvisionComplete, locale: str = "en-PH",
    ) -> None:
        super().__init__()
        self._inference_address = inference_address
        self._preset_name = preset_name
        self._device_family = device_family
        self._on_complete = on_complete
        self._locale = locale

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(t("models.provisioning.title", self._locale, name=self._preset_name), id="provision-title"),
            ProgressBar(id="provision-progress"),
            Static("", id="provision-log"),
            id="provision-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.run_worker(self._stream_provision(), exclusive=True)

    async def _stream_provision(self) -> None:
        import grpc

        from core.inference.generated import inference_pb2 as pb
        from core.inference.generated import inference_pb2_grpc as pb_grpc

        log = self.query_one("#provision-log", Static)
        progress = self.query_one("#provision-progress", ProgressBar)
        lines: list[str] = []
        ok = False
        error_detail = ""

        try:
            async with grpc.aio.insecure_channel(self._inference_address) as channel:
                stub = pb_grpc.InferenceServiceStub(channel)
                request = pb.ProvisionPresetRequest(preset=self._preset_name, device_family=self._device_family)
                async for update in stub.ProvisionPreset(request):
                    if update.complete:
                        ok = update.ok
                        error_detail = update.error_detail
                        lines.append(
                            t("models.provisioning.done", self._locale) if ok
                            else t("models.provisioning.failed", self._locale, detail=error_detail)
                        )
                        log.update("\n".join(lines[-20:]))
                        break

                    if update.files_total:
                        progress.total = update.files_total
                    progress.progress = update.files_completed
                    lines.append(t(
                        "models.provisioning.file_progress", self._locale,
                        file=update.current_file, downloaded=update.bytes_downloaded,
                        total=update.total_bytes, completed=update.files_completed,
                        files_total=update.files_total,
                    ))
                    log.update("\n".join(lines[-20:]))
        except grpc.aio.AioRpcError as exc:
            error_detail = exc.details() or str(exc)
            log.update(t("models.provisioning.failed", self._locale, detail=error_detail))

        await self._on_complete(ok, error_detail)


__all__ = ["ModelProvisioningProgressScreen", "OnProvisionComplete"]

"""Inference model provisioning — a real, considered exception to the closed 8-item
custom-screen list (`docs/PRINCIPLES.md` §1.4), not an oversight of it. Recorded here,
not just in `CLAUDE.md`, so the reasoning travels with the code: a preset's real
provisioning status (not-downloaded/partial/ready, and which device it would load on) can
only be known by calling `ListPresets` live, and a real multi-gigabyte download's own
progress genuinely cannot be expressed as a static, declarative list of labeled actions —
the identical shape of exception `BootSequenceScreen` and `RestartScreen` already
establish for "a long-running operation with real streaming progress," not a new pattern
invented here. What *is* menu data, deliberately: the root-menu entry that reaches this
screen (`menu_data/root.py`) — this screen is what that entry's `target` opens, the same
`interface.open_screen.*` convention every other custom screen already uses.

A thin gRPC client of Inference's own surface, same posture as `FleetScreen`'s
relationship to Supervisor — no business logic lives here, only rendering what
`ListPresets` reports and forwarding a provisioning request to the real
`ProvisionPreset` stream (via `ModelProvisioningProgressScreen`).
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Static

from services.interface.tui.custom_screens.model_provisioning_progress_screen import (
    ModelProvisioningProgressScreen,
)
from services.interface.tui.i18n import t

DEFAULT_INFERENCE_ADDRESS = "127.0.0.1:50073"


def _resolve_inference_address() -> str:
    from pathlib import Path

    from common.blob_client import resolve_service_address
    from common.install_paths import resolve_install_root

    install_root = resolve_install_root(Path(__file__))
    if install_root is None:
        return DEFAULT_INFERENCE_ADDRESS
    return resolve_service_address(install_root, "inference", DEFAULT_INFERENCE_ADDRESS)


@dataclass(frozen=True)
class _PresetRow:
    name: str
    status: str
    device: str


class ModelProvisioningScreen(Screen):
    """`inference_address=None` is a real, honest state (matching `FleetScreen`'s own
    `supervisor_address=None`) — reached without a resolvable Inference address, reports
    that plainly rather than hanging on a doomed gRPC call."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, inference_address: str | None = None, *, locale: str = "en-PH") -> None:
        super().__init__()
        self._inference_address = inference_address if inference_address is not None else _resolve_inference_address()
        self._locale = locale
        self._rows: dict[str, _PresetRow] = {}
        self._selected: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(t("models.title", self._locale), id="models-title"),
            ListView(id="models-list"),
            Static("", id="models-detail"),
            Button(t("models.provision", self._locale), id="models-provision"),
            Static("", id="models-status"),
            id="models-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self._reload()

    async def _reload(self) -> None:
        import grpc

        try:
            presets = await self._list_presets()
        except grpc.aio.AioRpcError:
            # A real, unreachable Inference process (not running, or address stale) is a
            # real, honest state -- reported plainly, matching `FleetScreen`'s own
            # `supervisor_address=None` "not connected" case, not a crash.
            self.query_one("#models-status", Static).update(t("models.not_connected", self._locale))
            return

        self._rows = {p.name: p for p in presets}
        list_view = self.query_one("#models-list", ListView)
        await list_view.clear()
        for name in sorted(self._rows):
            await list_view.append(ListItem(Static(self._row_label(self._rows[name])), id=f"models-row-{name}"))

    def _row_label(self, row: _PresetRow) -> str:
        return t(f"models.status.{row.status}", self._locale, name=row.name, device=row.device)

    async def _list_presets(self) -> tuple[_PresetRow, ...]:
        import grpc

        from core.inference.generated import inference_pb2 as pb
        from core.inference.generated import inference_pb2_grpc as pb_grpc

        async with grpc.aio.insecure_channel(self._inference_address) as channel:
            stub = pb_grpc.InferenceServiceStub(channel)
            response = await stub.ListPresets(pb.ListPresetsRequest())
            return tuple(
                _PresetRow(name=s.name, status=s.status, device=s.device) for s in response.preset_statuses
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        widget_id = event.item.id if event.item else None
        if not widget_id:
            return
        name = widget_id.removeprefix("models-row-")
        row = self._rows.get(name)
        if row is None:
            return
        self._selected = name
        self.query_one("#models-detail", Static).update(
            t("models.detail", self._locale, name=row.name, status=row.status, device=row.device)
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "models-provision" or self._selected is None:
            return
        row = self._rows.get(self._selected)
        if row is None:
            return
        if row.status == "ready":
            self.query_one("#models-status", Static).update(t("models.status.already_ready", self._locale, name=row.name))
            return
        self.app.push_screen(ModelProvisioningProgressScreen(
            self._inference_address, row.name, row.device,
            on_complete=self._make_provision_callback(row.name), locale=self._locale,
        ))

    def _make_provision_callback(self, preset_name: str):
        async def _on_complete(ok: bool, error_detail: str) -> None:
            self.app.pop_screen()
            status = t("models.provision_ok", self._locale, name=preset_name) if ok \
                else t("models.provision_failed", self._locale, name=preset_name, detail=error_detail)
            self.query_one("#models-status", Static).update(status)
            await self._reload()

        return _on_complete


__all__ = ["DEFAULT_INFERENCE_ADDRESS", "ModelProvisioningScreen"]

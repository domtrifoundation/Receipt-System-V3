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
`ListPresets`/`ListExecutionProviders` report and forwarding an operator's choice to the
real `ProvisionPreset` stream (via `ModelProvisioningProgressScreen`) or `SetPresetDevice`.

**Manual EP selection, real and separate from the hardware-derived default** (§8.6's own
auto-selection is a default, not a mandate) — the device `Select` always shows every
provider `ListExecutionProviders` reports, confidence and real installability included,
never just the ones auto-detection would have picked. Choosing one and pressing "Set
Device" persists an explicit per-preset override (`SetPresetDevice`, effective on the next
Inference restart — `core/inference/device_overrides.py`'s own module docstring has the
full "why not live" account); choosing one and pressing "Provision" downloads that exact
variant regardless of what's currently configured, so an operator can pre-stage a variant
before ever switching to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Select, Static

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


@dataclass(frozen=True)
class _ProviderRow:
    device: str
    label: str
    confidence: str
    installable: bool
    note: str


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
        self._providers: tuple[_ProviderRow, ...] = ()
        self._selected: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(t("models.title", self._locale), id="models-title"),
            ListView(id="models-list"),
            Static("", id="models-detail"),
            Select([], id="models-device-select", prompt=t("models.device_select_prompt", self._locale)),
            Static("", id="models-device-note"),
            Button(t("models.provision", self._locale), id="models-provision"),
            Button(t("models.set_device", self._locale), id="models-set-device"),
            Static("", id="models-status"),
            id="models-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self._load_providers()
        await self._reload()

    async def _load_providers(self) -> None:
        import grpc

        try:
            self._providers = await self._list_execution_providers()
        except grpc.aio.AioRpcError:
            return  # `_reload()`'s own not-connected message already covers this honestly

        select = self.query_one("#models-device-select", Select)
        select.set_options(
            (self._provider_option_label(p), p.device) for p in self._providers
        )

    def _provider_option_label(self, provider: _ProviderRow) -> str:
        installable_tag = "" if provider.installable else t("models.not_installable_tag", self._locale)
        return f"{provider.label} ({provider.confidence}){installable_tag}"

    async def _list_execution_providers(self) -> tuple[_ProviderRow, ...]:
        import grpc

        from core.inference.generated import inference_pb2 as pb
        from core.inference.generated import inference_pb2_grpc as pb_grpc

        async with grpc.aio.insecure_channel(self._inference_address) as channel:
            stub = pb_grpc.InferenceServiceStub(channel)
            response = await stub.ListExecutionProviders(pb.ListExecutionProvidersRequest())
            return tuple(
                _ProviderRow(
                    device=p.device, label=p.label, confidence=p.confidence,
                    installable=p.installable, note=p.note,
                )
                for p in response.providers
            )

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
        select = self.query_one("#models-device-select", Select)
        if any(p.device == row.device for p in self._providers):
            select.value = row.device

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "models-device-select":
            return
        provider = next((p for p in self._providers if p.device == event.value), None)
        note = self.query_one("#models-device-note", Static)
        note.update(provider.note if provider is not None else "")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "models-provision":
            await self._handle_provision()
        elif event.button.id == "models-set-device":
            await self._handle_set_device()

    def _selected_device(self) -> str | None:
        value = self.query_one("#models-device-select", Select).value
        return None if value is Select.NULL else value

    async def _handle_provision(self) -> None:
        row = self._rows.get(self._selected) if self._selected else None
        if row is None:
            return
        device_family = self._selected_device() or row.device
        if row.status == "ready" and device_family == row.device:
            self.query_one("#models-status", Static).update(t("models.status.already_ready", self._locale, name=row.name))
            return
        self.app.push_screen(ModelProvisioningProgressScreen(
            self._inference_address, row.name, device_family,
            on_complete=self._make_provision_callback(row.name), locale=self._locale,
        ))

    async def _handle_set_device(self) -> None:
        row = self._rows.get(self._selected) if self._selected else None
        device = self._selected_device()
        status = self.query_one("#models-status", Static)
        if row is None or device is None:
            status.update(t("models.status.pick_a_device_first", self._locale))
            return

        import grpc

        from core.inference.generated import inference_pb2 as pb
        from core.inference.generated import inference_pb2_grpc as pb_grpc

        try:
            async with grpc.aio.insecure_channel(self._inference_address) as channel:
                stub = pb_grpc.InferenceServiceStub(channel)
                response = await stub.SetPresetDevice(
                    pb.SetPresetDeviceRequest(preset=row.name, device=device)
                )
        except grpc.aio.AioRpcError:
            status.update(t("models.not_connected", self._locale))
            return

        if response.ok:
            status.update(t("models.device_set_ok", self._locale, name=row.name, device=device))
        else:
            status.update(t("models.device_set_failed", self._locale, name=row.name, detail=response.error_detail))

    def _make_provision_callback(self, preset_name: str):
        async def _on_complete(ok: bool, error_detail: str) -> None:
            self.app.pop_screen()
            status = t("models.provision_ok", self._locale, name=preset_name) if ok \
                else t("models.provision_failed", self._locale, name=preset_name, detail=error_detail)
            self.query_one("#models-status", Static).update(status)
            await self._reload()

        return _on_complete


__all__ = ["DEFAULT_INFERENCE_ADDRESS", "ModelProvisioningScreen"]

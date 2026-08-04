"""Fleet & Updates (`v3-deepdive-14-interface-api.md` §3.3, `v3-deepdive-38-supervisor.md`
§5) — on the enumerated custom-screen exception list, and a top-level root-menu item
(`menu_data/root.py`), sibling to Settings, never nested under it.

**Two genuinely different controls behind one screen, exactly matching the owning
spec.** Most services can have multiple versions marked *available* at once — this
screen's own version-list editor calls `SetAvailableVersions`, the real ceiling the
webapp's own end-user version choice is bounded by; actual concurrent instances are
started dynamically on real webapp demand (`supervisor.dynamic_start.
ensure_version_running`, reached via `StartVersion`), never all pre-started from here.
`interface_tui`/`inference` are the sole exceptions (`supervisor.available_versions.
SINGLE_INSTANCE_SERVICES`) — selecting either shows a single target-version field and
triggers a real, fullscreen `RestartScreen` instead of a version-list editor, since only
one instance of either can ever run.

A thin gRPC client of Supervisor's own surface, same posture as every other screen this
package ships — no business logic lives here, only rendering what Supervisor reports and
forwarding what the operator submits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, ListItem, ListView, Static

from services.interface.tui.custom_screens.restart_screen import RestartScreen
from services.interface.tui.i18n import t


@dataclass(frozen=True)
class _FleetRow:
    service_name: str
    single_instance: bool
    available_versions: tuple[str, ...] = ()
    running: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    """`(version, address)` for every instance `ListRunningInstances` reports for this service."""


class FleetScreen(Screen):
    """`supervisor_address=None` is a real, honest state — the screen was reached without
    a live Supervisor connection (e.g. a dev harness with no `--supervisor` arg) — and
    reports that plainly rather than hanging on a doomed gRPC call."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, supervisor_address: str | None, channel: str, *, locale: str = "en-PH") -> None:
        super().__init__()
        self._supervisor_address = supervisor_address
        self._channel = channel
        self._locale = locale
        self._rows: dict[str, _FleetRow] = {}
        self._selected: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(t("fleet.title", self._locale), id="fleet-title"),
            ListView(id="fleet-list"),
            Static("", id="fleet-detail"),
            Input(placeholder=t("fleet.input_placeholder", self._locale), id="fleet-version-input"),
            Button(t("fleet.apply", self._locale), id="fleet-apply"),
            Static("", id="fleet-status"),
            id="fleet-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        if self._supervisor_address is None:
            self.query_one("#fleet-status", Static).update(t("fleet.not_connected", self._locale))
            return
        await self._reload()

    async def _reload(self) -> None:
        from supervisor.available_versions import is_single_instance

        available = await self._list_available_versions()
        running: dict[str, list[tuple[str, str]]] = {}
        for entry in await self._list_running_instances():
            running.setdefault(entry.service_name, []).append((entry.version, entry.address))

        names = sorted(set(available) | set(running))
        self._rows = {
            name: _FleetRow(
                service_name=name, single_instance=is_single_instance(name),
                available_versions=tuple(available.get(name, ())),
                running=tuple(running.get(name, ())),
            )
            for name in names
        }

        list_view = self.query_one("#fleet-list", ListView)
        await list_view.clear()
        for name in names:
            await list_view.append(ListItem(Static(self._row_label(self._rows[name])), id=f"fleet-row-{name}"))

    def _row_label(self, row: _FleetRow) -> str:
        tag = t("fleet.single_instance_tag", self._locale) if row.single_instance else t("fleet.multi_instance_tag", self._locale)
        running_count = len(row.running)
        return f"{row.service_name} {tag} — {running_count} running, {len(row.available_versions)} available"

    async def _list_available_versions(self):
        import grpc

        from supervisor.generated import supervisor_pb2 as pb
        from supervisor.generated import supervisor_pb2_grpc as pb_grpc

        async with grpc.aio.insecure_channel(self._supervisor_address) as channel:
            stub = pb_grpc.SupervisorServiceStub(channel)
            response = await stub.ListAvailableVersions(pb.ChannelRequest(channel=self._channel))
            return {e.service_name: tuple(e.versions) for e in response.entries}

    async def _list_running_instances(self):
        import grpc

        from supervisor.generated import supervisor_pb2 as pb
        from supervisor.generated import supervisor_pb2_grpc as pb_grpc

        async with grpc.aio.insecure_channel(self._supervisor_address) as channel:
            stub = pb_grpc.SupervisorServiceStub(channel)
            response = await stub.ListRunningInstances(pb.ChannelRequest(channel=self._channel))
            return list(response.instances)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        widget_id = event.item.id if event.item else None
        if not widget_id:
            return
        name = widget_id.removeprefix("fleet-row-")
        row = self._rows.get(name)
        if row is None:
            return
        self._selected = name
        detail = self.query_one("#fleet-detail", Static)
        version_input = self.query_one("#fleet-version-input", Input)
        if row.single_instance:
            current = row.running[0][0] if row.running else ""
            detail.update(t("fleet.detail.single_instance", self._locale, service=name, current=current or t("fleet.detail.none_running", self._locale)))
            version_input.value = current
        else:
            detail.update(t(
                "fleet.detail.multi_instance", self._locale, service=name,
                available=", ".join(row.available_versions) or t("fleet.detail.none_available", self._locale),
                running=", ".join(v for v, _ in row.running) or t("fleet.detail.none_running", self._locale),
            ))
            version_input.value = ", ".join(row.available_versions)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "fleet-apply" or self._selected is None or self._supervisor_address is None:
            return
        row = self._rows.get(self._selected)
        if row is None:
            return
        raw = self.query_one("#fleet-version-input", Input).value
        status = self.query_one("#fleet-status", Static)

        if row.single_instance:
            target_version = raw.strip()
            if not target_version:
                status.update(t("fleet.status.empty_version", self._locale))
                return
            self.app.push_screen(RestartScreen(
                self._supervisor_address, row.service_name, target_version,
                on_complete=self._make_restart_callback(row.service_name, target_version), locale=self._locale,
            ))
            return

        versions = tuple(v.strip() for v in raw.split(",") if v.strip())
        await self._set_available_versions(row.service_name, versions)
        status.update(t("fleet.status.saved", self._locale, service=row.service_name))
        await self._reload()

    def _make_restart_callback(self, service_name: str, target_version: str):
        async def _on_complete(ok: bool, error_detail: str) -> None:
            self.app.pop_screen()
            status = t("fleet.status.restart_ok", self._locale, service=service_name, version=target_version) if ok \
                else t("fleet.status.restart_failed", self._locale, service=service_name, detail=error_detail)
            self.query_one("#fleet-status", Static).update(status)
            await self._reload()

        return _on_complete

    async def _set_available_versions(self, service_name: str, versions: tuple[str, ...]) -> None:
        import grpc

        from supervisor.generated import supervisor_pb2 as pb
        from supervisor.generated import supervisor_pb2_grpc as pb_grpc

        async with grpc.aio.insecure_channel(self._supervisor_address) as channel:
            stub = pb_grpc.SupervisorServiceStub(channel)
            await stub.SetAvailableVersions(pb.SetAvailableVersionsRequest(
                channel=self._channel, service_name=service_name, versions=list(versions), requested_by="tui-owner",
            ))


__all__ = ["FleetScreen"]

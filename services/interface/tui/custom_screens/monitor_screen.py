"""The real home/landing screen — shown before any menu selection, per the explicit
operator requirement that the first thing the TUI shows is a live view of "the whole
program's workings," not a bare list of labeled actions. V2 had the equivalent precedent
(`dashboard.py`, named in `services/interface/CLAUDE.md`'s own V2-lineage note); this is
V3's real version of it, built against Supervisor's own genuinely reachable RPCs rather
than fabricated placeholder numbers.

**On the enumerated custom-screen exception list by the same rule every other stateful
screen there follows** (`docs/PRINCIPLES.md` §1.4) — a live multi-panel status view is
exactly "not a flat list of labeled actions."

**What is real here, stated plainly, matching this project's own "never plausible-looking
data" discipline**: the active release, per-service sleep/health classification (`Supervisor.
GetSleepStatus`, one real call per fleet member), and every currently-tracked multi-version
instance (`Supervisor.ListRunningInstances`) are all live data from a real running
Supervisor. **Run counts are honestly reported as unavailable** — `ExecutionCoreService`
(`services/execution_core/execution_core.proto`) has no RPC that lists active runs, only
`GetRunStatus(run_id)` for a run whose id is already known, so this panel cannot show a
real number without inventing one. That gap is Execution Core's own to close, not
something this screen should paper over with a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from services.interface.tui.banners import header_line
from services.interface.tui.i18n import t

#: A real, live-found gRPC quirk worth naming here rather than rediscovering per screen:
#: Supervisor's own `SleepPolicy`/`ServiceState` enums serialize to plain lowercase
#: strings on the wire (`sleep_wake/classification.py`), so this dict is a direct,
#: unglamorous lookup — no enum re-parsing needed on this side of the RPC.
_STATE_ICON = {"running": "●", "sleeping": "◌", "starting": "◐", "stopped": "○", "failed": "✕"}


@dataclass(frozen=True)
class _MonitorSnapshot:
    connected: bool
    channel: str = ""
    release_dir: str = ""
    activated_at: str = ""
    service_states: tuple[tuple[str, str], ...] = ()
    """`(service_name, state)` for every fleet member Supervisor knows about."""
    running_instances: tuple[tuple[str, str, str], ...] = ()
    """`(service_name, version, address)` for every tracked multi-version instance."""
    error_detail: str = ""


class MonitorScreen(Screen):
    """The real landing screen. `supervisor_address=None` degrades honestly (no fleet to
    report on) rather than hanging on a doomed connection — the same posture
    `FleetScreen` already takes."""

    BINDINGS = [("m", "open_menu", "Menu"), ("r", "refresh", "Refresh"), ("q", "handle_quit", "Quit")]

    def __init__(
        self, supervisor_address: str | None, channel: str, *, on_open_menu, locale: str = "en-PH",
    ) -> None:
        super().__init__()
        self._supervisor_address = supervisor_address
        self._channel = channel
        self._on_open_menu = on_open_menu
        self._locale = locale

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            # The persistent codename header (`v3-plan-02-architecture.md`'s own "(b)
            # persistently at the top of the TUI's main menu navigation") — this screen is
            # the real landing point now, so the header lives here rather than only on the
            # menu screen it used to be attached to.
            Static(f"{header_line()} — {t('app.title', self._locale)}", id="monitor-header"),
            Grid(
                Static("", id="monitor-release"),
                Static("", id="monitor-services"),
                Static("", id="monitor-instances"),
                Static(t("monitor.runs.unavailable", self._locale), id="monitor-runs"),
                id="monitor-grid",
            ),
            id="monitor-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self.action_refresh()

    def action_open_menu(self) -> None:
        self._on_open_menu()

    def action_handle_quit(self) -> None:
        self.app.exit()

    async def action_refresh(self) -> None:
        snapshot = await self._collect_snapshot()
        self._render_snapshot(snapshot)

    async def _collect_snapshot(self) -> _MonitorSnapshot:
        if self._supervisor_address is None:
            return _MonitorSnapshot(connected=False)

        import grpc

        from supervisor.generated import supervisor_pb2 as pb
        from supervisor.generated import supervisor_pb2_grpc as pb_grpc

        async with grpc.aio.insecure_channel(self._supervisor_address) as channel:
            stub = pb_grpc.SupervisorServiceStub(channel)

            active = await stub.GetActiveRelease(pb.ChannelRequest(channel=self._channel))
            if active.error_code:
                return _MonitorSnapshot(connected=True, error_detail=active.error_detail)

            service_states: list[tuple[str, str]] = []
            try:
                from pathlib import Path

                from supervisor.fleet import build_fleet_specs

                specs = build_fleet_specs(Path(active.release_dir))
            except OSError:
                specs = ()
            for spec in specs:
                status = await stub.GetSleepStatus(pb.ServiceStatusRequest(service_name=spec.name))
                service_states.append((spec.name, status.state))

            running_response = await stub.ListRunningInstances(pb.ChannelRequest(channel=self._channel))
            running_instances = tuple(
                (i.service_name, i.version, i.address) for i in running_response.instances
            )

            return _MonitorSnapshot(
                connected=True, channel=active.channel, release_dir=active.release_dir,
                activated_at=active.activated_at, service_states=tuple(service_states),
                running_instances=running_instances,
            )

    def _render_snapshot(self, snapshot: _MonitorSnapshot) -> None:
        release_panel = self.query_one("#monitor-release", Static)
        services_panel = self.query_one("#monitor-services", Static)
        instances_panel = self.query_one("#monitor-instances", Static)

        if not snapshot.connected:
            release_panel.update(t("monitor.not_connected", self._locale))
            services_panel.update("")
            instances_panel.update("")
            return

        if snapshot.error_detail:
            release_panel.update(t("monitor.error", self._locale, detail=snapshot.error_detail))
            services_panel.update("")
            instances_panel.update("")
            return

        release_panel.update(t(
            "monitor.release", self._locale, channel=snapshot.channel,
            release_dir=snapshot.release_dir, activated_at=snapshot.activated_at,
        ))

        by_state: dict[str, int] = {}
        lines = [t("monitor.services.title", self._locale, count=len(snapshot.service_states))]
        for name, state in sorted(snapshot.service_states):
            by_state[state] = by_state.get(state, 0) + 1
            lines.append(f"  {_STATE_ICON.get(state, '?')} {name} — {state}")
        summary = ", ".join(f"{count} {state}" for state, count in sorted(by_state.items()))
        lines.insert(1, f"  ({summary})" if summary else "")
        services_panel.update("\n".join(lines))

        if snapshot.running_instances:
            instance_lines = [t("monitor.instances.title", self._locale, count=len(snapshot.running_instances))]
            for name, version, address in sorted(snapshot.running_instances):
                instance_lines.append(f"  {name} @ {version} — {address}")
        else:
            instance_lines = [t("monitor.instances.none", self._locale)]
        instances_panel.update("\n".join(instance_lines))


__all__ = ["MonitorScreen"]

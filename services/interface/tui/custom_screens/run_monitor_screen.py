"""Real live status of in-progress and recent runs (`settings.py`'s sibling root-menu
entry, `run_monitor`) — previously a `"not built yet"` placeholder because Execution
Core had no RPC to list active runs at all (only `GetRunStatus(run_id)` for a run whose
id was already known). `ListActiveRuns` (new) is what makes this screen buildable for
real; this screen is a thin display client of it plus the already-real streaming
`GetRunStatus`, same posture as every other screen in this package toward its own owning
API.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, ListItem, ListView, Static


class RunMonitorScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, *, address_override: str | None = None) -> None:
        super().__init__()
        self._address_override = address_override
        self._runs: dict[str, object] = {}

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Run Monitor", id="run-monitor-title"),
            ListView(id="run-monitor-list"),
            Static("", id="run-monitor-detail"),
            id="run-monitor-container",
        )
        yield Footer()

    def _resolve_address(self) -> str:
        if self._address_override is not None:
            return self._address_override
        from common.blob_client import resolve_service_address
        from common.install_paths import resolve_install_root

        install_root = resolve_install_root(Path(__file__))
        if install_root is None:
            return "127.0.0.1:50068"
        return resolve_service_address(install_root, "execution_core", "127.0.0.1:50068")

    async def on_mount(self) -> None:
        await self.action_refresh()

    async def action_refresh(self) -> None:
        import grpc

        from services.execution_core.generated import execution_core_pb2 as pb
        from services.execution_core.generated import execution_core_pb2_grpc as pb_grpc

        detail = self.query_one("#run-monitor-detail", Static)
        list_view = self.query_one("#run-monitor-list", ListView)

        try:
            async with grpc.aio.insecure_channel(self._resolve_address()) as channel:
                response = await pb_grpc.ExecutionCoreServiceStub(channel).ListActiveRuns(pb.ListActiveRunsRequest())
        except grpc.aio.AioRpcError as exc:
            detail.update(f"Could not reach Execution Core: {exc.details()}")
            return

        self._runs = {r.run_id: r for r in response.runs}
        await list_view.clear()
        if not response.runs:
            detail.update("No active runs.")
            return
        for r in response.runs:
            await list_view.append(ListItem(
                Static(f"{r.run_id} — user {r.user_id} — {r.state} — {r.receipt_count} receipt(s)"),
                id=f"run-{r.run_id}",
            ))
        detail.update("")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not event.item.id:
            return
        run_id = event.item.id.removeprefix("run-")
        self.run_worker(self._stream_status(run_id), exclusive=True)

    async def _stream_status(self, run_id: str) -> None:
        import grpc

        from services.execution_core.generated import execution_core_pb2 as pb
        from services.execution_core.generated import execution_core_pb2_grpc as pb_grpc

        detail = self.query_one("#run-monitor-detail", Static)
        async with grpc.aio.insecure_channel(self._resolve_address()) as channel:
            stub = pb_grpc.ExecutionCoreServiceStub(channel)
            async for frame in stub.GetRunStatus(pb.RunStatusRequest(run_id=run_id)):
                if frame.error_code:
                    detail.update(f"{run_id}: {frame.error_code} — {frame.error_detail}")
                    return
                detail.update(
                    f"{run_id} — {frame.state} — {frame.receipts_completed}/{frame.receipts_total} — {frame.current_stage_summary}"
                )
                if frame.state in ("shutting_down", "closing"):
                    return


__all__ = ["RunMonitorScreen"]

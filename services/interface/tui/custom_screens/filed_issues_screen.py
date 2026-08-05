"""Real, live status of every issue this install has filed with the developers
(`settings.diagnostics.filed_issues`) — the honest answer to "we should have stats about
when it reports anything to GitHub: link, status, whether a fix PR is already linked."

**A thin display client of Telemetrees' own `ListFiledIssues` RPC**, which does the real
live GitHub lookup per record server-side (`core/telemetrees/diagnostics/
github_status_client.py`) — this screen renders whatever comes back, the same posture
every other screen in this package takes toward its own owning API.

**Real, honestly empty until a detector exists.** `core/telemetrees/diagnostics/
contracts.py`'s own docstring is explicit: the ledger and live-status lookup this screen
renders are real and tested, but nothing in this codebase yet decides a diagnosed error
is worth filing and actually calls GitHub's issue-creation API. An empty list here is the
correct, honest state today — not a bug in this screen.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, ListItem, ListView, Static


class FiledIssuesScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, supervisor_address: str | None, channel: str, *, address_override: str | None = None) -> None:
        super().__init__()
        # Telemetrees is a real Core API with its own real address, discovered the same
        # way every other cross-service lookup in this package works
        # (`common/blob_client.resolve_service_address`) -- `supervisor_address`/
        # `channel` are unused here directly; kept for a consistent constructor shape
        # with the other real screens in case a future pass needs channel-scoped filing.
        self._supervisor_address = supervisor_address
        self._channel = channel
        #: Real, test-only escape hatch — points at a real ephemeral-port test server
        #: instead of resolving through `service_addresses.json`, the same seam every
        #: other screen's own tests use to avoid depending on a live installed fleet.
        self._address_override = address_override

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Reported Issues", id="filed-issues-title"),
            ListView(id="filed-issues-list"),
            Static("", id="filed-issues-detail"),
            id="filed-issues-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self.action_refresh()

    async def action_refresh(self) -> None:
        import grpc

        from common.blob_client import resolve_service_address
        from common.install_paths import resolve_install_root
        from core.telemetrees.generated import telemetrees_pb2 as pb
        from core.telemetrees.generated import telemetrees_pb2_grpc as pb_grpc
        from pathlib import Path

        if self._address_override is not None:
            address = self._address_override
        else:
            install_root = resolve_install_root(Path(__file__))
            address = "127.0.0.1:50088" if install_root is None else resolve_service_address(
                install_root, "telemetrees", "127.0.0.1:50088",
            )

        detail = self.query_one("#filed-issues-detail", Static)
        list_view = self.query_one("#filed-issues-list", ListView)

        try:
            async with grpc.aio.insecure_channel(address) as channel:
                response = await pb_grpc.TelemetreesServiceStub(channel).ListFiledIssues(
                    pb.ListFiledIssuesRequest()
                )
        except grpc.aio.AioRpcError as exc:
            detail.update(f"Could not reach Telemetrees: {exc.details()}")
            return

        if not response.known:
            detail.update("Unknown — no install root could be resolved (a dev checkout has no ledger to read).")
            return

        await list_view.clear()
        if not response.issues:
            detail.update("No issues have been filed by this install yet.")
            return

        for issue in response.issues:
            await list_view.append(ListItem(Static(self._row_label(issue)), id=f"issue-{issue.issue_number}"))
        detail.update("")

    @staticmethod
    def _row_label(issue) -> str:
        if issue.error_detail:
            return f"#{issue.issue_number} {issue.title} -- status unavailable: {issue.error_detail}"
        pr_note = f", {len(issue.linked_pr_numbers)} linked PR(s)" if issue.linked_pr_numbers else ""
        return f"#{issue.issue_number} {issue.title} -- {issue.state}{pr_note} -- {issue.url}"


__all__ = ["FiledIssuesScreen"]

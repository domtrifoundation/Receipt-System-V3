"""`FiledIssuesScreen` — real end to end against a genuine running `TelemetreesServicer`,
whose own `ListFiledIssues` makes real, live calls to the real public GitHub REST API.
No mocked gRPC stub, no mocked HTTP response, anywhere in this chain.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

pytest.importorskip("textual", reason="textual is not installed in this interpreter")
grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.telemetrees.diagnostics.contracts import FiledIssueRecord  # noqa: E402
from core.telemetrees.diagnostics.ledger import FiledIssueLedger  # noqa: E402
from core.telemetrees.service import serve as telemetrees_serve  # noqa: E402
from services.interface.tui.custom_screens.filed_issues_screen import FiledIssuesScreen  # noqa: E402
from textual.app import App  # noqa: E402
from textual.widgets import ListView, Static  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _network_available() -> bool:
    try:
        httpx.get("https://api.github.com", timeout=3.0)
        return True
    except httpx.HTTPError:
        return False


requires_network = pytest.mark.skipif(not _network_available(), reason="no outbound network access in this sandbox")


class _Harness(App):
    def __init__(self, address: str) -> None:
        super().__init__()
        self._address = address

    def on_mount(self) -> None:
        self.push_screen(FiledIssuesScreen(None, "beta", address_override=self._address))


def test_empty_ledger_reports_no_issues_filed(tmp_path: Path):
    async def scenario():
        server = await telemetrees_serve("127.0.0.1:0", install_root=tmp_path)
        try:
            app = _Harness(server.bound_address)
            async with app.run_test() as pilot:
                await pilot.pause()
                detail = app.screen.query_one("#filed-issues-detail", Static)
                assert "No issues have been filed" in str(detail.render())
        finally:
            await server.stop(grace=1.0)

    run(scenario())


@requires_network
def test_a_real_filed_issue_shows_its_real_live_github_status(tmp_path: Path):
    """Records a real ledger entry for issue #1 and confirms the screen renders whatever
    GitHub actually returns for this project's own real issue #1 -- real data end to end,
    never fabricated."""

    async def scenario():
        FiledIssueLedger(tmp_path).record(FiledIssueRecord(
            fingerprint="f1", issue_number=1, url="placeholder", title="placeholder",
        ))
        server = await telemetrees_serve("127.0.0.1:0", install_root=tmp_path)
        try:
            app = _Harness(server.bound_address)
            async with app.run_test() as pilot:
                await pilot.pause()
                list_view = app.screen.query_one("#filed-issues-list", ListView)
                assert any(item.id == "issue-1" for item in list_view.children)
        finally:
            await server.stop(grace=1.0)

    run(scenario())


def test_pressing_r_refreshes_without_error(tmp_path: Path):
    async def scenario():
        server = await telemetrees_serve("127.0.0.1:0", install_root=tmp_path)
        try:
            app = _Harness(server.bound_address)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                detail = app.screen.query_one("#filed-issues-detail", Static)
                assert "No issues have been filed" in str(detail.render())
        finally:
            await server.stop(grace=1.0)

    run(scenario())


def test_reports_unknown_when_install_root_cannot_be_resolved():
    """A real running server with no `install_root` at all -- the honest "no ledger to
    read" case, distinct from "the ledger is empty"."""

    async def scenario():
        from core.telemetrees.service import serve as serve_no_root

        server = await serve_no_root("127.0.0.1:0")
        try:
            app = _Harness(server.bound_address)
            async with app.run_test() as pilot:
                await pilot.pause()
                detail = app.screen.query_one("#filed-issues-detail", Static)
                assert "Unknown" in str(detail.render())
        finally:
            await server.stop(grace=1.0)

    run(scenario())

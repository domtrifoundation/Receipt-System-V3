"""`detect_and_file_silent_service_issues` — the real pipeline from Watchdog's own
`GetSilentServices` signal to a filed (deduplicated) issue. A fake `GitHubAppIssueFilingClient`
-conforming object stands in for real filing (no real GitHub App credentials exist in
this environment, same class of substitution `core/ingestion`'s own Drive tests already
use for the identical reason) -- Watchdog itself is real and live, never mocked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.health.service import serve as health_serve  # noqa: E402
from core.health.watchdog.kicks import KickRegistry  # noqa: E402
from core.health.watchdog.timeout_detector import TimeoutDetector  # noqa: E402
from core.telemetrees.diagnostics.detector import detect_and_file_silent_service_issues  # noqa: E402
from core.telemetrees.diagnostics.issue_filer import FileIssueResult  # noqa: E402
from core.telemetrees.diagnostics.ledger import FiledIssueLedger  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@dataclass
class FakeFiler:
    configured: bool = True
    next_issue_number: int = 100
    filed_titles: list = field(default_factory=list)

    def is_configured(self) -> bool:
        return self.configured

    async def file_issue(self, title: str, body: str) -> FileIssueResult:
        self.filed_titles.append(title)
        number = self.next_issue_number
        self.next_issue_number += 1
        return FileIssueResult(ok=True, issue_number=number, url=f"https://github.com/x/y/issues/{number}")


def test_returns_empty_when_filer_is_not_configured(tmp_path):
    async def scenario():
        server = health_serve("127.0.0.1:0")
        try:
            filer = FakeFiler(configured=False)
            filed = await detect_and_file_silent_service_issues(tmp_path, server.bound_address, filer=filer)
            assert filed == ()
        finally:
            server.stop(None)

    run(scenario())


def test_files_a_real_issue_for_a_genuinely_silent_service(tmp_path):
    async def scenario():
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        registry = KickRegistry(now=lambda: now)
        registry.kick("ocr", "instance-1")

        later = now + timedelta(minutes=10)
        detector = TimeoutDetector(registry, now=lambda: later)

        # A real server built directly from our own deterministic registry/detector
        # (rather than health_serve()'s own defaults), so the silence is real and
        # controlled rather than depending on wall-clock timing.
        from core.health.service import WatchdogServicer, HealthServicer
        import grpc as grpc_mod
        from core.health.generated import health_pb2_grpc as pb_grpc

        real_server = grpc_mod.aio.server()
        pb_grpc.add_HealthServiceServicer_to_server(HealthServicer(), real_server)
        pb_grpc.add_WatchdogServiceServicer_to_server(WatchdogServicer(kicks=registry, detector=detector), real_server)
        port = real_server.add_insecure_port("127.0.0.1:0")
        real_server.bound_address = f"127.0.0.1:{port}"
        await real_server.start()

        try:
            filer = FakeFiler()
            filed = await detect_and_file_silent_service_issues(tmp_path, real_server.bound_address, filer=filer)

            assert len(filed) == 1
            assert filed[0].fingerprint == "silent_service:ocr"
            assert filer.filed_titles == ["Service went silent: ocr"]

            ledger = FiledIssueLedger(tmp_path)
            assert len(ledger.list_all()) == 1
        finally:
            await real_server.stop(None)

    run(scenario())


def test_a_second_check_does_not_refile_the_same_silent_service(tmp_path):
    async def scenario():
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        registry = KickRegistry(now=lambda: now)
        registry.kick("ocr", "instance-1")
        later = now + timedelta(minutes=10)
        detector = TimeoutDetector(registry, now=lambda: later)

        import grpc as grpc_mod
        from core.health.service import WatchdogServicer, HealthServicer
        from core.health.generated import health_pb2_grpc as pb_grpc

        real_server = grpc_mod.aio.server()
        pb_grpc.add_HealthServiceServicer_to_server(HealthServicer(), real_server)
        pb_grpc.add_WatchdogServiceServicer_to_server(WatchdogServicer(kicks=registry, detector=detector), real_server)
        port = real_server.add_insecure_port("127.0.0.1:0")
        real_server.bound_address = f"127.0.0.1:{port}"
        await real_server.start()

        try:
            filer = FakeFiler()
            first = await detect_and_file_silent_service_issues(tmp_path, real_server.bound_address, filer=filer)
            second = await detect_and_file_silent_service_issues(tmp_path, real_server.bound_address, filer=filer)

            assert len(first) == 1
            assert len(second) == 0
            assert len(filer.filed_titles) == 1
        finally:
            await real_server.stop(None)

    run(scenario())


def test_no_silent_services_files_nothing(tmp_path):
    async def scenario():
        server = health_serve("127.0.0.1:0")
        try:
            filer = FakeFiler()
            filed = await detect_and_file_silent_service_issues(tmp_path, server.bound_address, filer=filer)
            assert filed == ()
            assert filer.filed_titles == []
        finally:
            server.stop(None)

    run(scenario())

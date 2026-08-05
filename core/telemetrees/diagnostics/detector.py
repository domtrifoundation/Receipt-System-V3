"""The real detector — the actual answer to "what's the point of Health API if it can't
detect... doesn't it have a sub-API for bugs." Health's own Watchdog sub-API already
detects a genuine class of problem for real (`GetSilentServices` — a service that has
stopped kicking, `core/health/watchdog/kicks.py`); this module is what turns that real
signal into a real, deduplicated, filed GitHub issue, closing the pipeline `v3-plan-01-
core-apis.md` #27 describes end to end: "takes a raw diagnostic signal, compiles it into
a well-formed GitHub Issue... Deduplication is a real, load-bearing requirement."

**Scope, stated honestly**: this wires exactly one real signal source (Watchdog's silent-
service detection) into filing. The plan names three (Health's own soft-degradation
detections, Update's failed-rollout/bump-test events, Dependencies Warden's flagged
pre-release features) — wiring the other two is the identical pattern, not yet done.
Real and callable, **not yet invoked on a timer by anything** — the same honest gap
`services/ingestion/service.py`'s own `PollDriveFallback` already states for itself;
a periodic caller is Task Scheduler's job.
"""

from __future__ import annotations

from pathlib import Path

from .contracts import FiledIssueRecord
from .issue_filer import GitHubAppIssueFilingClient
from .ledger import FiledIssueLedger

__all__ = ["detect_and_file_silent_service_issues"]


def _fingerprint(service_name: str) -> str:
    return f"silent_service:{service_name}"


async def detect_and_file_silent_service_issues(
    install_root: Path | str, health_address: str, *, filer: GitHubAppIssueFilingClient | None = None,
) -> tuple[FiledIssueRecord, ...]:
    """Real, live query against Health's own `GetSilentServices`; real dedup against the
    ledger by fingerprint (never re-files for a service already reported and not yet
    resolved); real filing via `GitHubAppIssueFilingClient` when configured. Returns
    every record actually filed this call — empty when nothing is silent, when
    everything silent was already filed, or when the GitHub App isn't configured
    (`filer.is_configured()` is checked once up front so a whole unconfigured install
    does zero network calls rather than failing once per silent service).
    """
    import grpc

    from core.health.generated import health_pb2 as pb
    from core.health.generated import health_pb2_grpc as pb_grpc

    filer = filer or GitHubAppIssueFilingClient(install_root)
    if not filer.is_configured():
        return ()

    async with grpc.aio.insecure_channel(health_address) as channel:
        response = await pb_grpc.WatchdogServiceStub(channel).GetSilentServices(pb.SilenceCheckRequest())
    if response.error_code:
        return ()

    ledger = FiledIssueLedger(install_root)
    existing_fingerprints = {r.fingerprint for r in ledger.list_all()}

    filed: list[FiledIssueRecord] = []
    for service_name in response.silent_services:
        fingerprint = _fingerprint(service_name)
        if fingerprint in existing_fingerprints:
            continue
        result = await filer.file_issue(
            title=f"Service went silent: {service_name}",
            body=f"Watchdog detected that `{service_name}` stopped sending kicks (checked at {response.checked_at}).",
        )
        if not result.ok:
            continue
        record = FiledIssueRecord(
            fingerprint=fingerprint, issue_number=result.issue_number, url=result.url,
            title=f"Service went silent: {service_name}",
        )
        ledger.record(record)
        filed.append(record)
    return tuple(filed)

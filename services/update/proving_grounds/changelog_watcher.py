"""A thin read surface over Telemetrees' own real `GetChangelog` RPC
(`core/telemetrees/service.py`, built this session) — **not in the deep-dive's own §2
package layout**, present in this folder's scaffold anyway; kept real rather than deleted
because it closes a genuine seam between Dependencies Warden's own "this exists now"
signal and a human deciding what is worth testing.

**Deliberately does not trigger anything.** `core/telemetrees/dependencies_warden/
CLAUDE.md` is explicit: "whether a surfaced change is program-important is a human call,
deliberately not automated from a changelog diff." This module's only job is surfacing
the real changelog text for a human to read — it builds no `TestCandidate`, calls no
`test_candidate()`, and has no opinion about what is worth testing. A future human-facing
surface (a CLI, a TUI screen) is what turns "I read this and decided it matters" into an
actual `TestCandidate`, not this module.
"""

from __future__ import annotations

__all__ = ["fetch_changelog"]

DEFAULT_TELEMETREES_ADDRESS = "127.0.0.1:50088"


async def fetch_changelog(address: str = DEFAULT_TELEMETREES_ADDRESS, *, timeout_seconds: float = 5.0) -> str:
    """The real, current `docs/CHANGELOG.md` content, fetched over gRPC from a running
    Telemetrees process. Never raises — an unreachable Telemetrees or a genuinely empty
    changelog both resolve to an empty string, which is the honest state either way from
    this caller's own point of view (it has no way to distinguish "nothing to show yet"
    from "couldn't ask" without more context than this thin function is worth carrying)."""
    try:
        import grpc

        from core.telemetrees.generated import telemetrees_pb2 as pb
        from core.telemetrees.generated import telemetrees_pb2_grpc as pb_grpc
    except ImportError:
        return ""

    try:
        async with grpc.aio.insecure_channel(address) as channel:
            stub = pb_grpc.TelemetreesServiceStub(channel)
            response = await stub.GetChangelog(pb.ChangelogRequest(), timeout=timeout_seconds)
    except Exception:  # noqa: BLE001 - unreachable/timeout degrades to empty, see docstring
        return ""

    if response.error_code:
        return ""
    return response.markdown

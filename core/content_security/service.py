"""The `ContentSecurityService` gRPC servicer — thin by design (§7).

Every real decision lives in `pipeline.py`, `scanning/` and `providers/`. This file translates
protobuf messages to and from `contracts.py` types and nothing else, which is what keeps the
fail-closed guarantee a property of the package rather than of this one file.

**That framing matters more here than in most packages.** §4 makes fail-closed a *contract-level*
guarantee precisely because "a security check that can be silently skipped under some failure
condition is, for practical purposes, not really a security check". So this module is written
so that no failure mode can produce anything other than a deny:

* Every RPC body is wrapped. An exception escaping to gRPC would abort the call with a status,
  and a caller's own `except` block is exactly where a silent bypass gets written by accident.
  The wrapper converts it to `safe=False` with an error code instead.
* There is no branch here that can set `safe=True`. That value only ever arrives from
  `ContentScanner`, which reaches it only after every enabled, available provider agreed.
* The `.proto` itself has no field capable of expressing "could not check" — see its header.

**Concurrency**: `grpc.server` with a thread pool, driving the async pipeline through
`asyncio.run` per call. §6 classifies this API as mixed — magic-byte and polyglot work is
CPU-bound over bytes already in memory, the provider scan is a subprocess or network call — so
the servicer stays synchronous and the async boundary sits where the actual I/O is.

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly as
`core/logs/service.py` does, so this package stays importable — and its tests meaningful — on
an interpreter with no `grpcio` wheel yet (3.15 today, per `docs/MAINTENANCE.md` §3).
"""

from __future__ import annotations

import asyncio
from concurrent import futures

from .contracts import ContainerScanRequest, ScanRequest, ScanVerdict
from .errors import ERROR_SUMMARIES, E_INVALID_REQUEST, ContentSecurityError
from .pipeline import ContentScanner
from .providers.base import ProviderRegistry

DEFAULT_ADDRESS = "127.0.0.1:50064"

#: What a caller sees when the servicer itself failed rather than a scan returning a verdict.
#: `safe` is absent from this constant on purpose — it is constructed as False at every use.
UNSCANNED_REASON = "the scan could not be completed, so this file is treated as unscanned"


def request_from_wire(message) -> ScanRequest:
    return ScanRequest(
        content=message.content,
        claimed_mime_type=message.claimed_mime_type,
        claimed_filename=message.claimed_filename,
        blob_ref=message.blob_ref,
        requesting_user_id=message.requesting_user_id or None,
        run_id=message.run_id or None,
    )


def container_request_from_wire(message) -> ContainerScanRequest:
    return ContainerScanRequest(
        content=message.content,
        claimed_filename=message.claimed_filename,
        blob_ref=message.blob_ref,
        requesting_user_id=message.requesting_user_id or None,
        run_id=message.run_id or None,
    )


def verdict_to_wire(verdict: ScanVerdict, pb):
    return pb.ScanVerdict(
        safe=verdict.safe,
        detected_type=verdict.detected_type,
        rejection_reason=verdict.rejection_reason,
        requires_staff_review=verdict.requires_staff_review,
        error_code=verdict.error_code,
        provider_verdicts=dict(verdict.provider_verdicts),
    )


class ContentSecurityServicer:
    """Implements `ContentSecurityService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(self, scanner: ContentScanner) -> None:
        self._scanner = scanner

    def ScanFile(self, request, context):  # noqa: N802 - gRPC method naming
        from .generated import content_security_pb2 as pb

        if not request.content:
            return pb.ScanVerdict(
                safe=False,
                rejection_reason=ERROR_SUMMARIES[E_INVALID_REQUEST],
                error_code=E_INVALID_REQUEST,
            )
        try:
            verdict = asyncio.run(self._scanner.scan(request_from_wire(request)))
        except (ContentSecurityError, Exception) as exc:  # noqa: B014 - see module docstring
            return pb.ScanVerdict(
                safe=False,
                rejection_reason=f"{UNSCANNED_REASON}: {exc}",
                error_code="SCAN_UNAVAILABLE",
            )
        return verdict_to_wire(verdict, pb)

    def ScanContainer(self, request, context):  # noqa: N802
        from .generated import content_security_pb2 as pb

        if not request.content:
            return pb.ContainerScanVerdict(
                safe=False,
                rejection_reason=ERROR_SUMMARIES[E_INVALID_REQUEST],
                error_code=E_INVALID_REQUEST,
            )
        try:
            verdict = asyncio.run(
                self._scanner.scan_container(container_request_from_wire(request))
            )
        except Exception as exc:  # see module docstring — never let this reach the caller
            return pb.ContainerScanVerdict(
                safe=False,
                rejection_reason=f"{UNSCANNED_REASON}: {exc}",
                error_code="SCAN_UNAVAILABLE",
            )
        bomb = verdict.bomb_check
        return pb.ContainerScanVerdict(
            safe=verdict.safe,
            bomb_check=pb.BombCheckResult(
                safe=bomb.safe,
                reason=bomb.reason,
                compression_ratio=bomb.compression_ratio,
                uncompressed_total_bytes=bomb.total_uncompressed_bytes,
                entry_count=bomb.entry_count,
                bad_entries=list(bomb.bad_entries),
            ),
            member_verdicts={
                name: verdict_to_wire(member, pb)
                for name, member in verdict.member_verdicts.items()
            },
            remediation=pb.RemediationResult(
                action=verdict.remediation.action,
                removed=list(verdict.remediation.removed),
            ),
            requires_staff_review=verdict.requires_staff_review,
            rejection_reason=verdict.rejection_reason,
            error_code=verdict.error_code,
        )


def serve(address: str = DEFAULT_ADDRESS, *, registry: ProviderRegistry | None = None):
    """Start the service. Returns the running server so a caller can stop it.

    An empty registry is a legitimate startup state and deliberately not an error: with no
    provider registered, every scan is denied with `NO_SCAN_PROVIDER_AVAILABLE`, which is the
    correct fail-closed answer. Refusing to start would instead take the whole service down
    and give Ingestion nothing to call — and a caller that cannot reach this service at all is
    exactly the outage §4 tells every caller to treat as unsafe anyway, so the strict-startup
    version buys nothing and costs a diagnosable error message.
    """
    import grpc

    from .generated import content_security_pb2_grpc as pb_grpc

    scanner = ContentScanner(registry or ProviderRegistry())
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_ContentSecurityServiceServicer_to_server(
        ContentSecurityServicer(scanner), server
    )
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import os
    import sys

    from .providers.clamav_provider import ClamAVProvider

    #: Real, previously-live-found gap: `serve()`'s own empty-registry default is a
    #: deliberate, correct fail-closed *fallback* (see its docstring), but nothing ever
    #: actually registered the deep-dive's own documented default provider here — meaning
    #: every real install, ClamAV present or not, denied every single upload forever.
    #: `ClamAVProvider.is_available()` already degrades to unavailable (still fail-closed,
    #: §4.4) when `clamscan` isn't on PATH, so registering it unconditionally is safe on a
    #: self-hosted box that doesn't have ClamAV installed — it just changes nothing for that
    #: box, while finally letting the intended default actually take effect where it exists.
    #:
    #: `RESIBO_CLAMAV_DATABASE_DIR` overrides `clamscan`'s own baked-in database path —
    #: real, live-found reason: that default sits next to the binary itself
    #: (`Program Files\ClamAV\database` on Windows), which is TrustedInstaller/
    #: Administrators-owned and unwritable by the ordinary account this service actually
    #: runs as, so `freshclam` has nowhere it can put current definitions without an
    #: operator explicitly redirecting both tools at a directory the service account owns.
    default_registry = ProviderRegistry()
    default_registry.register(
        ClamAVProvider(database_dir=os.environ.get("RESIBO_CLAMAV_DATABASE_DIR"))
    )

    addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
    srv = serve(addr, registry=default_registry)
    print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
    print(f"ContentSecurityService listening on {srv.bound_address}", file=sys.stderr)
    print(f"running under: {sys.executable} ({sys.version.split()[0]})", file=sys.stderr)
    from common.watchdog_client import ThreadedKicker
    kicker = ThreadedKicker('content_security')
    try:
        srv.wait_for_termination()
    finally:
        kicker.stop()

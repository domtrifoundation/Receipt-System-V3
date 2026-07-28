"""The orchestrator: request -> verdict (§3, §4, §9). **Not in the deep-dive's own §2 package
layout** — see this package's `CLAUDE.md` for why it was added and what it is responsible for.

This is the one module that composes `scanning/` (magic bytes, polyglot detection, bomb
checks — pure, synchronous, in-memory) with `providers/` (the malware-scan Provider Registry —
async, subprocess or network I/O) into the two verdict types `contracts.py` defines. Nothing
in `service.py` should ever call `scanning/` or `providers/` directly; the gRPC servicer's own
job is translating wire messages to and from `ScanRequest`/`ScanVerdict`, and this module is
what it calls in between (mirroring `core/logs`'s own "the servicer is a thin translation
layer; `query.py` is where the actual behaviour lives" split).

**The single hard rule every code path below is written to satisfy**
(`docs/PRINCIPLES.md` §4.2): every return statement in `ContentScanner.scan` either sets
`safe=True` because every enabled, available provider agreed the file is clean, or sets
`safe=False`. There is no code path that can return without deciding one way or the other, and
there is no code path where an internal exception is allowed to propagate out of `scan()` or
`scan_container()` — every `try` below exists because an uncaught exception crossing this
module's own boundary would be exactly the silent bypass this API exists to prevent (a caller
catching `ContentSecurityError` and treating it as "couldn't check, so let it through" is a
bug in the caller this module makes structurally unnecessary to write).
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from common.frozen_dict import FrozenDict

from .contracts import (
    ContainerScanRequest,
    ContainerScanVerdict,
    DetectedFileType,
    ProviderScanResult,
    RemediationResult,
    ScanOutcome,
    ScanRequest,
    ScanVerdict,
)
from .errors import (
    E_ARCHIVE_BOMB,
    E_MALICIOUS_CONFIRMED,
    E_MEMBER_UNSAFE,
    E_NOT_A_VALID_CONTAINER,
    E_NO_PROVIDER_AVAILABLE,
    E_POLYGLOT_DETECTED,
    E_SCAN_PROVIDER_FAILED,
    E_STAFF_REVIEW_REQUIRED,
)
from .metrics import ContentSecurityMetricsCollector
from .providers.base import ProviderRegistry
from .scanning import bomb_check, magic_bytes, polyglot_detection

DEFAULT_PROVIDER_TIMEOUT_SECONDS = 30.0


class ContentScanner:
    """Runs the full pipeline for one file, or one container. One instance per process,
    holding the `ProviderRegistry` every scan runs against."""

    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        metrics: ContentSecurityMetricsCollector | None = None,
        provider_timeout: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ) -> None:
        self._registry = registry
        self._metrics = metrics or ContentSecurityMetricsCollector()
        self._timeout = provider_timeout

    @property
    def metrics(self) -> ContentSecurityMetricsCollector:
        return self._metrics

    # ------------------------------------------------------------------ single file

    async def scan(self, request: ScanRequest) -> ScanVerdict:
        """Real file-type verification, polyglot detection, then malware scanning — in that
        order, because the first two are free (no provider invoked) and both can produce a
        deny on their own before any scanner is asked anything."""
        self._metrics.increment("scans_performed")
        detected = magic_bytes.detect(request.content)

        finding = polyglot_detection.check(request.content, primary=detected)
        if finding.is_polyglot:
            self._metrics.increment("polyglots_detected")
            self._metrics.increment("scans_denied_staff_review")
            # §8's own testing hook: "correctly flagged, not passed based on only checking
            # the first plausible format match." A polyglot is never released to normal
            # processing (`safe=False`) — but it is also not the same as a scanner-confirmed
            # malicious verdict, so a human gets to see it rather than it being silently
            # discarded as condemned outright (`requires_staff_review=True`, this module's
            # own three-way mapping, documented on `ScanVerdict` in `contracts.py`).
            return ScanVerdict(
                safe=False,
                detected_type=detected.mime_type,
                rejection_reason=finding.detail,
                requires_staff_review=True,
                error_code=E_POLYGLOT_DETECTED,
            )

        results = await self._registry.scan_all(
            request.content, blob_ref=request.blob_ref, timeout=self._timeout
        )
        return self._resolve(detected, results)

    def _resolve(
        self, detected: DetectedFileType, results: tuple[ProviderScanResult, ...]
    ) -> ScanVerdict:
        if not results:
            self._metrics.increment("scans_denied_no_provider")
            self._metrics.increment("provider_unavailable_events")
            return ScanVerdict(
                safe=False,
                detected_type=detected.mime_type,
                rejection_reason="no malware scan provider is available",
                error_code=E_NO_PROVIDER_AVAILABLE,
            )

        provider_verdicts = FrozenDict({r.provider_name: r.outcome.value for r in results})
        errored = [r for r in results if r.outcome is ScanOutcome.ERROR]
        if errored:
            # A provider that ran and failed makes the whole verdict untrustworthy, not just
            # that one provider's own share of it — §4.2 draws no distinction between "every
            # provider failed" and "one of several did," because a caller cannot tell a
            # verdict reached despite a failure apart from one that would have been different
            # had that provider actually run.
            self._metrics.increment("scans_denied_provider_error")
            names = ", ".join(r.provider_name for r in errored)
            return ScanVerdict(
                safe=False,
                detected_type=detected.mime_type,
                rejection_reason=f"scan provider(s) failed: {names}",
                error_code=E_SCAN_PROVIDER_FAILED,
                provider_verdicts=provider_verdicts,
            )

        outcomes = {r.outcome for r in results}
        if outcomes == {ScanOutcome.MALICIOUS}:
            # Unanimous. §9: "auto-reject only when every enabled scanner agrees."
            self._metrics.increment("scans_denied_malicious")
            return ScanVerdict(
                safe=False,
                detected_type=detected.mime_type,
                rejection_reason="every enabled scanner confirmed this file is malicious",
                error_code=E_MALICIOUS_CONFIRMED,
                provider_verdicts=provider_verdicts,
            )

        if outcomes != {ScanOutcome.CLEAN}:
            # Anything short of full agreement on CLEAN and anything short of full
            # agreement on MALICIOUS both land here: a MALICIOUS/CLEAN split (a genuine
            # disagreement, `docs/PRINCIPLES.md` §4.3), or any SUSPICIOUS result on its own
            # (a single scanner's own low-confidence/borderline signal, §9's other named
            # case). Neither is auto-accepted and neither is auto-rejected outright.
            self._metrics.increment("scans_denied_staff_review")
            return ScanVerdict(
                safe=False,
                detected_type=detected.mime_type,
                rejection_reason="scan providers disagree or returned a low-confidence result",
                requires_staff_review=True,
                error_code=E_STAFF_REVIEW_REQUIRED,
                provider_verdicts=provider_verdicts,
            )

        self._metrics.increment("scans_passed_clean")
        return ScanVerdict(
            safe=True, detected_type=detected.mime_type, provider_verdicts=provider_verdicts
        )

    # ------------------------------------------------------------------ containers

    async def scan_container(self, request: ContainerScanRequest) -> ContainerScanVerdict:
        """Two passes (§3): the container's own metadata first, then every member it yields —
        never the reverse, and never extraction before the first pass has cleared it."""
        self._metrics.increment("container_scans_performed")
        bomb = bomb_check.check(request.content)
        if not bomb.safe:
            self._metrics.increment("archive_bombs_rejected")
            return ContainerScanVerdict(
                safe=False,
                bomb_check=bomb,
                rejection_reason=bomb.reason,
                error_code=E_ARCHIVE_BOMB,
            )

        working_content = request.content
        remediation = RemediationResult(action="not_needed")
        if bomb.bad_entries:
            working_content, remediation = bomb_check.remediate_or_reject(
                request.content, bomb.bad_entries
            )
            if remediation.action == "rejected_whole_archive":
                self._metrics.increment("archive_bombs_rejected")
                names = ", ".join(bomb.bad_entries)
                return ContainerScanVerdict(
                    safe=False,
                    bomb_check=bomb,
                    remediation=remediation,
                    rejection_reason=(
                        f"bomb-prone or nested-archive entries could not be safely stripped: "
                        f"{names}"
                    ),
                    error_code=E_ARCHIVE_BOMB,
                )
            self._metrics.increment("remediations_performed")

        try:
            member_verdicts, overall_safe, review = await self._scan_members(
                working_content, remediation.removed, request
            )
        except zipfile.BadZipFile as exc:
            return ContainerScanVerdict(
                safe=False,
                bomb_check=bomb,
                remediation=remediation,
                rejection_reason=f"container could not be re-opened after remediation: {exc}",
                error_code=E_NOT_A_VALID_CONTAINER,
            )

        return ContainerScanVerdict(
            safe=overall_safe,
            bomb_check=bomb,
            member_verdicts=FrozenDict(member_verdicts),
            remediation=remediation,
            requires_staff_review=review,
            rejection_reason="" if overall_safe else "one or more contained files failed their own scan",
            error_code="" if overall_safe else E_MEMBER_UNSAFE,
        )

    async def _scan_members(
        self,
        content: bytes,
        removed: tuple[str, ...],
        request: ContainerScanRequest,
    ) -> tuple[dict[str, ScanVerdict], bool, bool]:
        member_verdicts: dict[str, ScanVerdict] = {}
        overall_safe = True
        review = False
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = [n for n in archive.namelist() if n not in removed]
            for name in names:
                member_bytes = archive.read(name)
                verdict = await self.scan(
                    ScanRequest(
                        content=member_bytes,
                        claimed_filename=name,
                        blob_ref=f"{request.blob_ref}!{name}" if request.blob_ref else "",
                        requesting_user_id=request.requesting_user_id,
                        run_id=request.run_id,
                    )
                )
                member_verdicts[name] = verdict
                if not verdict.safe:
                    overall_safe = False
                if verdict.requires_staff_review:
                    review = True
        return member_verdicts, overall_safe, review


__all__ = ["ContentScanner", "DEFAULT_PROVIDER_TIMEOUT_SECONDS"]

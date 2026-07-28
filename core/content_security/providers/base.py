"""`MalwareScanProvider` — the Provider Registry for malware/exploit scanning (§2, §5.1, §9).

**Corrected during a principles-compliance audit, per the deep-dive's own §2 note**: an
earlier version of this package had malware scanning as a single `malware_scan.py` module
despite §5.1 and §9 both describing ClamAV and a cloud scanner as genuinely swappable
alternatives that should run *simultaneously* and be cross-checked — a real
`docs/PRINCIPLES.md` §1.2/§1.3 violation, not a stylistic preference. This is the real
Provider Registry that correction produced.

**More than one provider runs at once, by design, exactly as OCR's own engines do.** That is
not decoration: §9's own "auto-reject only on unanimous agreement, disagreement routes to
staff review" resolution is structurally *impossible* without more than one provider's own
answer to compare — a single scanner has nothing to disagree with. `ProviderRegistry.scan_all`
is what makes that comparison possible; `pipeline.py` is where the comparison itself (the
consensus rule) actually happens, kept out of this file the same way `core/logs`'s
`SinkRegistry` fans an entry out to every sink without itself knowing what a sink does with it.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from ..contracts import ProviderScanResult, ScanOutcome


@runtime_checkable
class MalwareScanProvider(Protocol):
    """One malware-scanning backend — a local subprocess, a cloud API, or any future
    provider a self-hosted install wants to point at its own scanner instead."""

    @property
    def name(self) -> str:
        """Stable identifier, used as the registry key and in `ScanVerdict.provider_verdicts`."""

    async def scan(self, content: bytes, *, blob_ref: str = "") -> ProviderScanResult:
        """Scan one file's bytes. Never raises: any internal failure is caught and returned
        as `ProviderScanResult(outcome=ScanOutcome.ERROR, ...)` — a provider that raised out
        of this method instead would still be caught by `ProviderRegistry.scan_all`'s own
        defensive wrapper (§4.4, the same "a sink is not necessarily one of this package's
        own" reasoning `core/logs`'s `LogWriter.write_sync` applies to third-party sinks), but
        a well-behaved provider does not rely on that safety net.
        """

    async def is_available(self) -> bool:
        """Whether this provider can be invoked right now — a missing local binary or an
        unconfigured API key, not "did the last scan succeed" (§4.4's graceful degradation).
        A provider reporting itself unavailable is excluded from `scan_all`'s own run
        entirely, the same way an OCR engine that never started is excluded from that run.
        """


class ProviderRegistry:
    """A genuinely mutable registry populated at startup, so a plain `dict`
    (`docs/PRINCIPLES.md` §2.1.1) — the same distinction `core/logs`'s `SinkRegistry` and
    `core/persistence/archive_sync`'s `SyncProviderRegistry` both draw.
    """

    def __init__(self) -> None:
        self._providers: dict[str, MalwareScanProvider] = {}
        self._enabled: set[str] = set()

    def register(self, provider: MalwareScanProvider, *, enabled: bool = True) -> None:
        self._providers[provider.name] = provider
        if enabled:
            self._enabled.add(provider.name)
        else:
            self._enabled.discard(provider.name)

    def enable(self, name: str) -> bool:
        if name not in self._providers:
            return False
        self._enabled.add(name)
        return True

    def disable(self, name: str) -> None:
        self._enabled.discard(name)

    def get(self, name: str) -> MalwareScanProvider | None:
        return self._providers.get(name)

    def enabled(self) -> tuple[MalwareScanProvider, ...]:
        return tuple(self._providers[n] for n in sorted(self._enabled))

    async def scan_all(
        self, content: bytes, *, blob_ref: str = "", timeout: float = 30.0
    ) -> tuple[ProviderScanResult, ...]:
        """Run every enabled, *available* provider concurrently and return every result.

        Availability is checked first, per provider, so a provider that is not configured at
        all (no API key, no binary found) never gets counted as a scan that ran and produced
        nothing — it is simply absent from the returned tuple, exactly the same shape
        `pipeline.py` sees when it later has to distinguish "no provider is available at all"
        (`errors.NoProviderAvailable`, an outright deny) from "providers ran and disagreed"
        (`requires_staff_review`).

        **A provider that times out or raises is never dropped from the result set.** It
        becomes a real `ScanOutcome.ERROR` entry instead — dropping it silently would let a
        crashed scanner look, from `pipeline.py`'s point of view, identical to a scanner that
        was simply never enabled, which is exactly the ambiguity §4.2 forbids: a failed check
        must be distinguishable as *attempted and failed*, not silently absent.
        """
        candidates = self.enabled()
        available: list[MalwareScanProvider] = []
        for provider in candidates:
            try:
                is_up = await asyncio.wait_for(provider.is_available(), timeout=timeout)
            except Exception:  # noqa: BLE001 - a crashing availability check is "not available"
                is_up = False
            if is_up:
                available.append(provider)

        if not available:
            return ()

        return tuple(
            await asyncio.gather(
                *(self._scan_one(provider, content, blob_ref, timeout) for provider in available)
            )
        )

    @staticmethod
    async def _scan_one(
        provider: MalwareScanProvider, content: bytes, blob_ref: str, timeout: float
    ) -> ProviderScanResult:
        try:
            return await asyncio.wait_for(
                provider.scan(content, blob_ref=blob_ref), timeout=timeout
            )
        except TimeoutError:
            return ProviderScanResult(
                provider_name=provider.name,
                outcome=ScanOutcome.ERROR,
                detail=f"scan timed out after {timeout}s",
            )
        except Exception as exc:  # noqa: BLE001 - see this method's own docstring above
            return ProviderScanResult(
                provider_name=provider.name,
                outcome=ScanOutcome.ERROR,
                detail=f"{type(exc).__name__}: {exc}",
            )


__all__ = ["MalwareScanProvider", "ProviderRegistry"]

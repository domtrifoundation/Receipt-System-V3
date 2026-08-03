"""`SourceRegistry` — the Provider Registry mapping `SourceKind` -> `IngestionSource`
(deep-dive §1-§2). Every source is independently enableable; a self-hosted install with
no Drive configured degrades to direct-upload-only cleanly, never errors.

**`enabled_sources()` takes a `user_id`/`run_id` context, unused today, on purpose**
(deep-dive §1's own stated forward-compatible shape): today this reads a single global
`sources_enabled` config list, but the signature already matches what "resolve this run's
tier profile, read its sources list" will need once Architect's tier-profile registry
exists — swapping the resolution source is a change entirely inside this one method, not a
redesign of how any source or caller reports/consumes availability.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import SourceKind
from .sources.base import IngestionSource

__all__ = ["SourceRegistryConfig", "SourceRegistry"]

DEFAULT_SOURCES_ENABLED: frozenset[SourceKind] = frozenset(
    {SourceKind.DIRECT_UPLOAD, SourceKind.GOOGLE_DRIVE}
)


@dataclass(frozen=True)
class SourceRegistryConfig:
    sources_enabled: frozenset[SourceKind] = field(default_factory=lambda: DEFAULT_SOURCES_ENABLED)


class SourceRegistry:
    def __init__(
        self, sources: dict[SourceKind, IngestionSource], config: SourceRegistryConfig | None = None
    ) -> None:
        self._sources = sources
        self._config = config or SourceRegistryConfig()

    def get(self, kind: SourceKind) -> IngestionSource | None:
        return self._sources.get(kind)

    async def _one_availability(self, kind: SourceKind) -> bool:
        source = self._sources.get(kind)
        if source is None:
            return False
        try:
            return await source.is_available()
        except Exception:  # noqa: BLE001 - a probe failure means unavailable, not a crash
            return False

    async def available_sources(self) -> frozenset[SourceKind]:
        import asyncio

        kinds = tuple(self._sources)
        results = await asyncio.gather(*(self._one_availability(k) for k in kinds))
        return frozenset(k for k, available in zip(kinds, results) if available)

    async def enabled_sources(self, user_id: str = "", run_id: str = "") -> frozenset[SourceKind]:
        """`user_id`/`run_id` are accepted and unused today — see the module docstring."""
        available = await self.available_sources()
        return available & self._config.sources_enabled

"""`SourceRegistry` (deep-dive §1-§2) — availability probing and the
`available ∩ enabled` shape every Provider Registry in this project uses."""

from __future__ import annotations

from core.ingestion.contracts import SourceKind
from core.ingestion.source_registry import SourceRegistry, SourceRegistryConfig

from .conftest import run


class _FakeSource:
    def __init__(self, kind: SourceKind, available: bool) -> None:
        self._kind = kind
        self._available = available

    @property
    def source(self) -> SourceKind:
        return self._kind

    async def is_available(self) -> bool:
        return self._available


def test_available_sources_reflects_live_probes():
    registry = SourceRegistry({
        SourceKind.DIRECT_UPLOAD: _FakeSource(SourceKind.DIRECT_UPLOAD, True),
        SourceKind.GOOGLE_DRIVE: _FakeSource(SourceKind.GOOGLE_DRIVE, False),
    })
    available = run(registry.available_sources())
    assert available == {SourceKind.DIRECT_UPLOAD}


def test_enabled_sources_is_available_intersect_config():
    registry = SourceRegistry(
        {
            SourceKind.DIRECT_UPLOAD: _FakeSource(SourceKind.DIRECT_UPLOAD, True),
            SourceKind.GOOGLE_DRIVE: _FakeSource(SourceKind.GOOGLE_DRIVE, True),
        },
        SourceRegistryConfig(sources_enabled=frozenset({SourceKind.DIRECT_UPLOAD})),
    )
    enabled = run(registry.enabled_sources(user_id="u1", run_id="r1"))
    assert enabled == {SourceKind.DIRECT_UPLOAD}


def test_a_probe_that_raises_is_treated_as_unavailable_not_a_crash():
    class _CrashingSource:
        source = SourceKind.GOOGLE_DRIVE

        async def is_available(self):
            raise RuntimeError("boom")

    registry = SourceRegistry({SourceKind.GOOGLE_DRIVE: _CrashingSource()})
    available = run(registry.available_sources())
    assert available == frozenset()

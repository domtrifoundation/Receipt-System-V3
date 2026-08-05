"""`drive_assembly.py` — the real, complete gap this closes: `GoogleDriveSource` and its
credential providers each existed and were independently tested, but nothing ever
constructed a `GoogleDriveSource` and registered it into the running service's own
`SourceRegistry`. Confirms the credential-strategy switch is real and that
`IngestionServicer` now genuinely registers a Drive source (unavailable, correctly, since
nothing is configured in these tests).
"""

from __future__ import annotations

from core.ingestion.contracts import SourceKind
from core.ingestion.drive_assembly import GoogleDriveConfig, build_credential_provider, build_google_drive_source
from core.ingestion.service import IngestionServicer
from core.ingestion.sources.google_drive.oauth import OAuthCredentialProvider
from core.ingestion.sources.google_drive.service_account import ServiceAccountCredentialProvider

from .conftest import run


def test_build_credential_provider_defaults_to_service_account():
    provider = build_credential_provider(GoogleDriveConfig())
    assert isinstance(provider, ServiceAccountCredentialProvider)


def test_build_credential_provider_selects_oauth_when_configured():
    provider = build_credential_provider(GoogleDriveConfig(credential_strategy="oauth"))
    assert isinstance(provider, OAuthCredentialProvider)


def test_build_credential_provider_degrades_an_unknown_strategy_to_the_default():
    provider = build_credential_provider(GoogleDriveConfig(credential_strategy="not-a-real-strategy"))
    assert isinstance(provider, ServiceAccountCredentialProvider)


def test_build_google_drive_source_is_registered_and_reports_unavailable_unconfigured(blob_store):
    config = GoogleDriveConfig()
    credentials = build_credential_provider(config)
    source = build_google_drive_source(credentials, config, blob_store)
    assert source.source == SourceKind.GOOGLE_DRIVE
    assert run(source.is_available()) is False


def test_ingestion_servicer_genuinely_registers_a_google_drive_source(blob_store):
    """The concrete fix: `IngestionServicer`'s own `SourceRegistry` used to only ever
    contain `SourceKind.DIRECT_UPLOAD` — Drive was completely unreachable through the
    running service regardless of configuration."""
    servicer = IngestionServicer(blob_store)
    assert SourceKind.GOOGLE_DRIVE in servicer._registry._sources
    available = run(servicer._registry.available_sources())
    assert available == frozenset({SourceKind.DIRECT_UPLOAD})

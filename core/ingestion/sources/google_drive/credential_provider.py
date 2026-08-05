"""`DriveCredentialProvider` — the swappable interface behind Drive access (deep-dive
§4.1.1). Two implementations exist: `ServiceAccountCredentialProvider` (the only one
actually usable today) and `OAuthCredentialProvider` (implemented, held inactive behind
config until Google's OAuth app-verification process clears — a real, separate piece of
work outside this package's own scope, not a design gap here).

`GoogleDriveSource` (`drive_source.py`) never branches on which strategy is active — that
is the entire point of this Protocol, and `tests/unit/core/ingestion/test_google_drive.py`
carries a regression test that stands the source up against both providers mocked
identically to keep this honest over time (deep-dive §10).
"""

from __future__ import annotations

from typing import Any, Protocol

__all__ = ["DriveCredentialProvider"]


class DriveCredentialProvider(Protocol):
    def get_service(self) -> Any:
        """Returns an authenticated Drive v3 service object (`googleapiclient.discovery.
        Resource`). Raises `core.ingestion.errors.SourceUnavailable` if credentials
        aren't configured or the client library isn't installed."""
        ...

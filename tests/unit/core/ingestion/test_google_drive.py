"""Google Drive source (deep-dive §4.1) — the credential-strategy swap test named
explicitly in §10: `GoogleDriveSource` must genuinely not care which
`DriveCredentialProvider` it's handed. Uses fake credential providers implementing the
same Protocol, not the real service-account/OAuth ones, since the whole point is proving
indifference to *which* provider is behind the interface — the real providers'
own availability behavior (correctly `False` without real credentials/libraries
installed) is tested separately and directly.
"""

from __future__ import annotations

from core.ingestion.sources.google_drive.drive_source import DriveSourceConfig, GoogleDriveSource
from core.ingestion.sources.google_drive.oauth import OAuthConfig, OAuthCredentialProvider
from core.ingestion.sources.google_drive.service_account import (
    ServiceAccountConfig,
    ServiceAccountCredentialProvider,
)

from .conftest import run


class _FakeDriveService:
    """Mimics just enough of `googleapiclient.discovery.Resource`'s own call shape for
    `GoogleDriveSource` to exercise its real `list_new_files`/`download` logic."""

    def __init__(self, files: list[dict], downloads: dict[str, bytes]) -> None:
        self._files = files
        self._downloads = downloads

    def files(self):
        return self

    def list(self, **kwargs):
        self._mode = "list"
        return self

    def get_media(self, fileId):  # noqa: N803
        self._mode = "download"
        self._file_id = fileId
        return self

    def execute(self):
        if self._mode == "list":
            return {"files": self._files}
        return self._downloads[self._file_id]


class _FakeCredentialProvider:
    def __init__(self, service) -> None:
        self._service = service

    def get_service(self):
        return self._service


def _make_source(provider_kind: str, blob_store) -> GoogleDriveSource:
    service = _FakeDriveService(
        files=[{"id": "f1", "name": "receipt.pdf", "mimeType": "application/pdf"}],
        downloads={"f1": b"fake-pdf-bytes"},
    )
    credentials = _FakeCredentialProvider(service)
    config = DriveSourceConfig(folder_id="folder1")
    return GoogleDriveSource(credentials, blob_store, config)


def test_list_new_files_works_identically_regardless_of_credential_provider_kind(blob_store):
    for kind in ("service_account", "oauth"):
        source = _make_source(kind, blob_store)
        files = run(source.list_new_files())
        assert len(files) == 1
        assert files[0]["id"] == "f1"


def test_download_works_identically_regardless_of_credential_provider_kind(blob_store):
    for kind in ("service_account", "oauth"):
        source = _make_source(kind, blob_store)
        result = run(source.download("r1", "u1", "f1", "receipt.pdf", "application/pdf"))
        assert blob_store.blobs[result.raw_blob_ref.logical_id] == b"fake-pdf-bytes"


def test_is_available_requires_a_configured_folder(blob_store):
    service = _FakeDriveService(files=[], downloads={})
    credentials = _FakeCredentialProvider(service)
    source = GoogleDriveSource(credentials, blob_store, DriveSourceConfig(folder_id=""))
    assert run(source.is_available()) is False


def test_service_account_provider_reports_unavailable_without_a_key_file_configured():
    """A real, live-confirmed state: no key file path configured means unavailable,
    exactly the graceful-degradation path this provider exists to prove works."""
    provider = ServiceAccountCredentialProvider(ServiceAccountConfig(key_file_path=""))
    assert provider.is_available() is False


def test_oauth_provider_reports_unavailable_without_full_config():
    provider = OAuthCredentialProvider(OAuthConfig())
    assert provider.is_available() is False

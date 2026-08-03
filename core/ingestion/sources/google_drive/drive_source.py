"""Google Drive as an Ingestion source (deep-dive §4.1.2) — independent of which
credential strategy is active (`credential_provider.py`'s own Protocol).

**Not live-tested this session** — no real Drive folder/credentials/network call was
made; see `service_account.py`'s own module docstring for why. Built directly from
`googleapiclient`'s own published Drive v3 API shape (`files().list()`/`files().get_
media()`), the same honesty posture every other unverified-library-call module in this
session's work takes.

`googleapiclient`'s Drive client is a synchronous, blocking HTTP client — every call here
dispatches through `run_in_executor`, matching every other blocking-native/HTTP-call case
in this project's design (deep-dive §7.1 names this as the one genuine I/O-bound-but-
still-blocking exception in an otherwise fully-`async` API).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ...contracts import BlobStoreGateway, SourceFile, SourceKind
from ...errors import DownloadFailed, SourceUnavailable
from .credential_provider import DriveCredentialProvider

__all__ = ["DriveSourceConfig", "GoogleDriveSource"]

#: File-type filtering at the Drive API query level (deep-dive §4.1.2) — a cheap first
#: filter narrowing the poll/webhook payload before anything reaches Content Security,
#: never a substitute for it (declared MIME type is still never trusted past this point).
_SUPPORTED_MIME_TYPES = (
    "application/pdf", "image/jpeg", "image/png", "image/tiff", "image/bmp", "image/webp",
    "image/heic", "image/heif",
)


@dataclass(frozen=True)
class DriveSourceConfig:
    folder_id: str = ""  # the shared folder to poll/watch — empty = not configured
    page_size: int = 50


def _list_new_files_sync(service, folder_id: str, page_size: int) -> list[dict]:
    mime_query = " or ".join(f"mimeType='{m}'" for m in _SUPPORTED_MIME_TYPES)
    query = f"'{folder_id}' in parents and ({mime_query}) and trashed=false"
    response = service.files().list(
        q=query, pageSize=page_size, fields="files(id, name, mimeType)"
    ).execute()
    return response.get("files", [])


def _download_sync(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id)
    return request.execute()


class GoogleDriveSource:
    def __init__(
        self,
        credentials: DriveCredentialProvider,
        blob_store: BlobStoreGateway,
        config: DriveSourceConfig | None = None,
    ) -> None:
        self._credentials = credentials
        self._blob_store = blob_store
        self._config = config or DriveSourceConfig()

    @property
    def source(self) -> SourceKind:
        return SourceKind.GOOGLE_DRIVE

    async def is_available(self) -> bool:
        if not self._config.folder_id:
            return False
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._credentials.get_service)
        except SourceUnavailable:
            return False
        return True

    async def list_new_files(self) -> tuple[dict, ...]:
        """Fallback poll path (deep-dive §4.1.2) — the primary trigger is the Webhook
        Subscription Manager's push notification; this exists for Circadian's own
        much-less-frequent safety-net poll and for an install with webhooks disabled."""
        if not self._config.folder_id:
            raise SourceUnavailable("no Drive folder configured")
        loop = asyncio.get_running_loop()
        service = await loop.run_in_executor(None, self._credentials.get_service)
        try:
            files = await loop.run_in_executor(
                None, _list_new_files_sync, service, self._config.folder_id, self._config.page_size
            )
        except Exception as exc:  # noqa: BLE001 - any Drive API failure is a download failure
            raise DownloadFailed(f"Drive files.list failed: {exc}") from exc
        return tuple(files)

    async def download(self, run_id: str, user_id: str, file_id: str, filename: str, mime_type: str) -> SourceFile:
        loop = asyncio.get_running_loop()
        service = await loop.run_in_executor(None, self._credentials.get_service)
        try:
            data = await loop.run_in_executor(None, _download_sync, service, file_id)
        except Exception as exc:  # noqa: BLE001 - any Drive API failure is a download failure
            raise DownloadFailed(f"Drive files.get_media failed: {exc}") from exc

        raw_ref = await self._blob_store.write_blob(data)
        return SourceFile(
            run_id=run_id, user_id=user_id, source=self.source,
            raw_blob_ref=raw_ref, original_filename=filename, declared_mime_type=mime_type,
        )

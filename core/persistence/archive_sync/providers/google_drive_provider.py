"""Google Drive mirror target — the default provider (§3).

The only file in this repository that knows the Drive client library exists. The import is
lazy and its absence degrades this provider to unreachable rather than failing an install
that never mirrors anything (`docs/PRINCIPLES.md` §3.3 point 5, §4.4).

Credentials are **reused from the ingestion grant** through `credential_reuse.py` — this
provider never initiates its own authorization flow, which is the whole point of one
authorization rather than two.
"""

from __future__ import annotations

from typing import Any

from ..contracts import SyncResult
from ..credential_reuse import DriveGrant
from ..errors import TARGET_MISSING, UPLOAD_FAILED


class GoogleDriveProvider:
    """Implements `SyncTargetProvider`."""

    name = "google_drive"

    def __init__(self, grant: DriveGrant | None, folder_id: str, fetch_bytes) -> None:
        self._grant = grant
        self._folder_id = folder_id
        self._fetch = fetch_bytes
        self._service: Any | None = None
        self._unavailable = "" if grant else "no reusable Drive grant"

    def _load(self) -> Any | None:
        if self._service is not None or self._grant is None:
            return self._service
        try:
            from googleapiclient.discovery import build  # noqa: PLC0415
            from google.oauth2.credentials import Credentials  # noqa: PLC0415
        except ImportError as exc:
            self._unavailable = f"google api client not installed ({exc})"
            return None
        try:
            creds = Credentials(token=self._grant.token_ref, scopes=list(self._grant.scopes))
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        except Exception as exc:  # noqa: BLE001
            self._unavailable = f"drive client init failed ({exc})"
            return None
        return self._service

    async def is_reachable(self) -> bool:
        """A deleted or access-revoked target folder is a real, checkable state.

        It reports False rather than raising, which is what lets the sync job notify and
        pause instead of retrying into a folder that is not coming back (§8).
        """
        service = self._load()
        if service is None:
            return False
        try:
            service.files().get(fileId=self._folder_id, fields="id").execute()
        except Exception:  # noqa: BLE001
            return False
        return True

    async def mirror(self, blob_ref: str, target_path: str) -> SyncResult:
        service = self._load()
        if service is None:
            return SyncResult(
                ok=False, error_code=TARGET_MISSING, error_detail=self._unavailable
            )
        data = await self._fetch(blob_ref)
        if data is None:
            return SyncResult(
                ok=False, error_code=UPLOAD_FAILED, error_detail=f"no bytes for {blob_ref}"
            )
        try:
            from googleapiclient.http import MediaInMemoryUpload  # noqa: PLC0415

            service.files().create(
                body={"name": target_path, "parents": [self._folder_id]},
                media_body=MediaInMemoryUpload(data),
                fields="id",
            ).execute()
        except Exception as exc:  # noqa: BLE001
            return SyncResult(ok=False, error_code=UPLOAD_FAILED, error_detail=str(exc))
        return SyncResult(ok=True, external_name=target_path)


__all__ = ["GoogleDriveProvider"]

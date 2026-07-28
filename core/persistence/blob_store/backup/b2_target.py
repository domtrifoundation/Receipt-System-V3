"""Backblaze B2 backup target — the one adapter that knows `b2sdk` exists (§1.3).

Nothing else in this repository imports the B2 SDK. That is the whole point of the adapter
rule: a library bump's blast radius is this file, which is what makes the Proving Grounds
dependency-update loop tractable at all.

**The import is lazy and its absence is a degradation, not a failure** (`docs/PRINCIPLES.md`
§3.3 point 5, §4.4). A self-hosted install with no B2 account never pays the import cost and
never sees an error; the target simply reports itself unreachable and the registry's
one-of-N durability rule carries the write on whatever other target is configured. Backup is
not a security check, so degrading is correct here — the fail-closed rule (§4.2) applies to
Content Security, not to replication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import TargetOutcome


@dataclass(frozen=True)
class B2Config:
    """Credentials come from config, never from a literal in this file."""

    key_id: str
    application_key: str
    bucket_name: str
    prefix: str = "blobs"


class B2Target:
    """Implements `BackupTarget`. Structural typing — no inheritance from the Protocol."""

    name = "b2"

    def __init__(self, config: B2Config | None = None) -> None:
        self._config = config
        self._bucket: Any | None = None
        self._unavailable_reason = "" if config else "b2 is not configured"

    def _load(self) -> Any | None:
        """Resolve the SDK and bucket handle on first real use, not at import time."""
        if self._bucket is not None or self._config is None:
            return self._bucket
        try:
            from b2sdk.v2 import B2Api, InMemoryAccountInfo  # noqa: PLC0415
        except ImportError as exc:
            self._unavailable_reason = f"b2sdk not installed ({exc})"
            return None
        try:
            api = B2Api(InMemoryAccountInfo())
            api.authorize_account("production", self._config.key_id, self._config.application_key)
            self._bucket = api.get_bucket_by_name(self._config.bucket_name)
        except Exception as exc:  # noqa: BLE001 - any SDK failure is "unreachable", not fatal
            self._unavailable_reason = f"b2 authorization failed ({exc})"
            return None
        return self._bucket

    def _key(self, physical_hash: str) -> str:
        prefix = self._config.prefix if self._config else "blobs"
        return f"{prefix}/{physical_hash[:2]}/{physical_hash[2:4]}/{physical_hash}"

    async def is_reachable(self) -> bool:
        return self._load() is not None

    async def upload(self, physical_hash: str, data: bytes) -> TargetOutcome:
        bucket = self._load()
        if bucket is None:
            return TargetOutcome(self.name, ok=False, error_detail=self._unavailable_reason)
        try:
            bucket.upload_bytes(data, self._key(physical_hash))
        except Exception as exc:  # noqa: BLE001
            return TargetOutcome(self.name, ok=False, error_detail=str(exc))
        return TargetOutcome(self.name, ok=True)

    async def fetch(self, physical_hash: str) -> bytes | None:
        bucket = self._load()
        if bucket is None:
            return None
        try:
            downloaded = bucket.download_file_by_name(self._key(physical_hash))
            return downloaded.response.content
        except Exception:  # noqa: BLE001
            return None


__all__ = ["B2Config", "B2Target"]

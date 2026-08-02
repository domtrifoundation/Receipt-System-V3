"""Storj backup target, via its S3-compatible gateway — the one adapter that knows `boto3`.

Same shape and same reasoning as `b2_target.py`: lazy import, absence is a degradation, and
this is the only file in the repository that imports the S3 client for this purpose.

Storj and B2 are both enabled at once by design — this is the `docs/PRINCIPLES.md` §1.2
"multiple simultaneous providers" case, not a primary-with-failover arrangement. Either one
alone is real durability; both confirming is the stronger `fully_synced` state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import TargetOutcome


@dataclass(frozen=True)
class StorjConfig:
    access_key: str
    secret_key: str
    bucket_name: str
    endpoint_url: str = "https://gateway.storjshare.io"
    prefix: str = "blobs"


class StorjTarget:
    """Implements `BackupTarget`."""

    name = "storj"

    def __init__(self, config: StorjConfig | None = None) -> None:
        self._config = config
        self._client: Any | None = None
        self._unavailable_reason = "" if config else "storj is not configured"

    def _load(self) -> Any | None:
        if self._client is not None or self._config is None:
            return self._client
        try:
            import boto3  # noqa: PLC0415
        except ImportError as exc:
            self._unavailable_reason = f"boto3 not installed ({exc})"
            return None
        try:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._config.endpoint_url,
                aws_access_key_id=self._config.access_key,
                aws_secret_access_key=self._config.secret_key,
            )
        except Exception as exc:  # noqa: BLE001
            self._unavailable_reason = f"storj client init failed ({exc})"
            return None
        return self._client

    def _key(self, physical_hash: str) -> str:
        prefix = self._config.prefix if self._config else "blobs"
        return f"{prefix}/{physical_hash[:2]}/{physical_hash[2:4]}/{physical_hash}"

    async def is_reachable(self) -> bool:
        client = self._load()
        if client is None or self._config is None:
            return False
        try:
            client.head_bucket(Bucket=self._config.bucket_name)
        except Exception:  # noqa: BLE001
            return False
        return True

    async def upload(self, physical_hash: str, data: bytes) -> TargetOutcome:
        client = self._load()
        if client is None or self._config is None:
            return TargetOutcome(self.name, ok=False, error_detail=self._unavailable_reason)
        try:
            client.put_object(
                Bucket=self._config.bucket_name, Key=self._key(physical_hash), Body=data
            )
        except Exception as exc:  # noqa: BLE001
            return TargetOutcome(self.name, ok=False, error_detail=str(exc))
        return TargetOutcome(self.name, ok=True)

    async def fetch(self, physical_hash: str) -> bytes | None:
        client = self._load()
        if client is None or self._config is None:
            return None
        try:
            obj = client.get_object(
                Bucket=self._config.bucket_name, Key=self._key(physical_hash)
            )
            return obj["Body"].read()
        except Exception:  # noqa: BLE001
            return None


__all__ = ["StorjConfig", "StorjTarget"]

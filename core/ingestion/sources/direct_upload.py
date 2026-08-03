"""Direct upload (deep-dive §4.2) — the simplest source mechanically: no push/poll
uncertainty, no third-party reliability question. Gateway already authenticated the
browser's POST via session cookie and forwards the raw bytes over internal gRPC; this
source's whole job is staging those bytes as a `SourceFile` for the shared Content
Security -> Format Normalization pipeline every other source also feeds into.

Always available — no external dependency, no credentials, nothing to degrade. This is
the reasonable always-on default (deep-dive §1) and the fallback path Gateway calls
directly regardless of which other sources are configured.
"""

from __future__ import annotations

from ..contracts import BlobStoreGateway, SourceFile, SourceKind

__all__ = ["DirectUploadSource"]


class DirectUploadSource:
    def __init__(self, blob_store: BlobStoreGateway) -> None:
        self._blob_store = blob_store

    @property
    def source(self) -> SourceKind:
        return SourceKind.DIRECT_UPLOAD

    async def is_available(self) -> bool:
        return True

    async def receive(
        self, run_id: str, user_id: str, filename: str, declared_mime_type: str, data: bytes
    ) -> SourceFile:
        """Stages the already-received bytes as a `SourceFile` — no format decoding, no
        Content Security check here (that's the shared pipeline step every source's own
        output goes through identically, deep-dive §6)."""
        raw_ref = await self._blob_store.write_blob(data)
        return SourceFile(
            run_id=run_id, user_id=user_id, source=self.source,
            raw_blob_ref=raw_ref, original_filename=filename,
            declared_mime_type=declared_mime_type,
        )

"""`DirectUploadSource` (deep-dive §4.2) — the simplest source."""

from __future__ import annotations

from core.ingestion.contracts import SourceKind
from core.ingestion.sources.direct_upload import DirectUploadSource

from .conftest import run


def test_is_always_available(blob_store):
    source = DirectUploadSource(blob_store)
    assert run(source.is_available()) is True
    assert source.source == SourceKind.DIRECT_UPLOAD


def test_receive_stages_bytes_and_returns_a_source_file(blob_store):
    source = DirectUploadSource(blob_store)
    result = run(source.receive("r1", "u1", "receipt.jpg", "image/jpeg", b"fake-jpeg-bytes"))
    assert result.source == SourceKind.DIRECT_UPLOAD
    assert result.original_filename == "receipt.jpg"
    assert result.declared_mime_type == "image/jpeg"
    assert blob_store.blobs[result.raw_blob_ref.logical_id] == b"fake-jpeg-bytes"

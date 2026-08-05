"""Ingestion API data contracts (`v3-deepdive-04-ingestion-api.md` §3).

This is the only module in this package other APIs import from. Same "errors are data,
not exceptions" convention as the prior three APIs built this session — a per-file or
per-page failure populates `.error` rather than raising across the API boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from common.frozen_dict import FrozenDict


class SourceKind(str, Enum):
    DIRECT_UPLOAD = "direct_upload"
    GOOGLE_DRIVE = "google_drive"
    SCANNER = "scanner"


class IngestionErrorCode(str, Enum):
    SOURCE_NOT_CONFIGURED = "source_not_configured"
    SOURCE_UNAVAILABLE = "source_unavailable"
    CONTENT_SECURITY_REJECTED = "content_security_rejected"
    CONTENT_SECURITY_UNAVAILABLE = "content_security_unavailable"  # fail-closed — see errors.py
    UNSUPPORTED_FORMAT = "unsupported_format"
    NORMALIZATION_FAILED = "normalization_failed"
    STITCH_FAILED = "stitch_failed"
    ARCHIVE_ENTRY_FAILED = "archive_entry_failed"
    DOWNLOAD_FAILED = "download_failed"


@dataclass(frozen=True)
class IngestionError:
    code: IngestionErrorCode
    detail: str = ""


@dataclass(frozen=True)
class BlobRef:
    """Re-declared rather than imported from `core.persistence.contracts`, same reasoning
    as OCR's/Preprocessing's/Inference's own `contracts.BlobRef` — this package's
    `BlobStoreGateway` Protocol only ever needs `.logical_id`."""

    logical_id: str


@dataclass(frozen=True)
class SourceFile:
    run_id: str
    user_id: str
    source: SourceKind
    #: The as-received bytes, pre-normalization, pre-Content-Security-clearance — a
    #: TEMPORARY staging blob (deep-dive §3), not necessarily retained under Persistence's
    #: permanent `BlobLocation` mapping the way `NormalizationResult.archival_blob_ref` is.
    raw_blob_ref: BlobRef
    original_filename: str
    #: Client-supplied, never trusted — Content Security determines the real type.
    declared_mime_type: str


@dataclass(frozen=True)
class NormalizedImage:
    image_ref: BlobRef | None  # a finished, base image ready for Preprocessing/OCR
    page_index: int = 0  # for multi-page sources (PDF, multi-photo panorama)
    source: SourceKind = SourceKind.DIRECT_UPLOAD
    error: IngestionError | None = None


@dataclass(frozen=True)
class NormalizationResult:
    images: tuple[NormalizedImage, ...]  # one or more — a PDF or a panorama capture yields several
    archival_blob_ref: BlobRef | None  # the re-encoded archival copy, stored independently
    error: IngestionError | None = None


class BlobStoreGateway(Protocol):
    """The whole surface this package's sources/format-normalization code need from
    Persistence — same minimal shape as the prior three APIs' own `BlobStoreGateway`
    Protocols (`docs/PRINCIPLES.md` §1.3: a Protocol seam, not a shared type)."""

    async def read_blob(self, ref: BlobRef) -> bytes: ...
    async def write_blob(self, data: bytes) -> BlobRef: ...


@dataclass(frozen=True)
class IngestionMetrics:
    files_ingested: int = 0
    files_rejected_by_content_security: int = 0
    normalization_failed_count: int = 0
    stitch_failed_count: int = 0
    drive_downloads: int = 0
    scan_sessions_started: int = 0
    scan_sessions_finalized: int = 0


__all__ = [
    "BlobRef",
    "BlobStoreGateway",
    "IngestionError",
    "IngestionErrorCode",
    "IngestionMetrics",
    "NormalizationResult",
    "NormalizedImage",
    "SourceFile",
    "SourceKind",
]

"""Format Normalization's own error taxonomy — internal to this sub-package.

This sub-API has no gRPC surface of its own (no `service.py` in its package layout); the
parent `core/ingestion/` package is the only caller, and its own `service.py`/pipeline
code is the one place these get caught and converted into the parent's own
`contracts.IngestionError` (mirroring every other API's single-conversion-point
convention this session — `core/ocr/engine_registry.py`, `core/preprocessing/
generation.py`).
"""

from __future__ import annotations

__all__ = [
    "ArchiveExtractFailed",
    "CodecEncodeFailed",
    "FormatNormalizationInternalError",
    "RasterFailed",
    "UnsupportedFormat",
]


class FormatNormalizationInternalError(Exception):
    """Base for everything this sub-package raises internally."""


class RasterFailed(FormatNormalizationInternalError):
    """PDF rendering or image decode genuinely failed."""


class UnsupportedFormat(FormatNormalizationInternalError):
    """The source file's format isn't one this sub-package's raster/codec path handles."""


class CodecEncodeFailed(FormatNormalizationInternalError):
    """The archival re-encode (AVIF/WebP) failed — a corrupt decoded image, an
    unsupported pixel mode, an encoder-level failure."""


class ArchiveExtractFailed(FormatNormalizationInternalError):
    """A zip/bulk-upload batch could not be opened or enumerated at all — distinct from
    one bad *entry* inside an otherwise-good archive, which is the parent package's own
    `ArchiveEntryFailed` (per-entry, not per-archive)."""

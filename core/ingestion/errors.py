"""Ingestion API's error taxonomy.

`IngestionError` (`contracts.py`) is the wire-facing shape — never raised across this
API's own gRPC boundary (`docs/PRINCIPLES.md` §4.1). The exception classes below exist for
the *internal* call path only.

**`ContentSecurityUnavailable` is the one deliberate fail-closed exception in this
package** (deep-dive §6): every other failure here degrades gracefully or reports a data
error, but a file that can't be verified safe must never be processed just because the
verifier was slow or unreachable. `source_registry.py`/`format_normalization`'s own
pipeline treats this one specifically as "reject the file," never "skip the check."
"""

from __future__ import annotations

__all__ = [
    "ArchiveEntryFailed",
    "ContentSecurityRejected",
    "ContentSecurityUnavailable",
    "DownloadFailed",
    "IngestionInternalError",
    "NormalizationFailed",
    "SourceNotConfigured",
    "SourceUnavailable",
    "StitchFailed",
    "UnsupportedFormat",
]


class IngestionInternalError(Exception):
    """Base for everything this package raises internally, never across its own boundary."""


class SourceNotConfigured(IngestionInternalError):
    """The requested source isn't in `sources_enabled` at all — a caller error, discovered
    before any provider is even touched."""


class SourceUnavailable(IngestionInternalError):
    """A configured source's own dependency/credentials aren't usable right now (missing
    Drive API client library, no service-account key configured) — degrades that one
    source to unavailable (`docs/PRINCIPLES.md` §4.4), never fails the whole registry."""


class ContentSecurityRejected(IngestionInternalError):
    """Content Security scanned the file and found it unsafe — a real, data-carried
    rejection, not a transport failure."""


class ContentSecurityUnavailable(IngestionInternalError):
    """Content Security itself could not be reached or timed out. **Fail closed**: this is
    the one place in this package where "the verifier was unavailable" must be treated
    the same as "the file failed the scan," never as "skip the check and proceed."""


class UnsupportedFormat(IngestionInternalError):
    """The source file's format isn't one Format Normalization's own raster/codec path
    handles at all."""


class NormalizationFailed(IngestionInternalError):
    """Format Normalization genuinely failed to produce a base image — a corrupt file, a
    decode library error."""


class StitchFailed(IngestionInternalError):
    """`cv2.Stitcher` reported a real failure status (deep-dive §4.3.2) — carries the
    specific `cv2.Stitcher` status code so the caller can surface the right guidance
    ("need more images" vs. "bad match, retake this section")."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        super().__init__(detail or f"stitch failed with status {status_code}")
        self.status_code = status_code


class ArchiveEntryFailed(IngestionInternalError):
    """One entry inside a zip/bulk-upload batch failed Content Security or normalization —
    carries which entry, so a partially-bad batch can report per-entry results rather than
    failing the whole upload (deep-dive §5's Python 3.16+ selective-remediation note)."""


class DownloadFailed(IngestionInternalError):
    """A source's own download call (Drive API, in particular) failed at the transport
    level."""

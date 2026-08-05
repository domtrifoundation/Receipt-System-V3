"""Preprocessing API's error taxonomy.

`PreprocessingError` is the wire-facing shape (`contracts.RasterResult.error`,
`contracts.Variant.error`) — never raised across this API's own gRPC boundary
(`docs/PRINCIPLES.md` §4.1). Preprocessing has no equivalent of Auth's raise-loudly carve-out:
nothing here is a security decision, and a caller that got a `None` variant this run is
strictly better served by a data-carried error than by an exception.

The exception classes below exist for the *internal* call path only — `raster.py`,
`generation.py` and the individual `variants/` modules raise these, and the one place they get
caught and converted into a `PreprocessingError` is `generation.py`'s own worker-function
boundary (mirroring how `core/geo_address/corroboration.py` is the one conversion point for its
own provider exceptions).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "PreprocessingError",
    "PreprocessingErrorCode",
    "RasterFailed",
    "UnsupportedFormat",
    "VariantGenerationFailed",
]


class PreprocessingErrorCode(str, Enum):
    RASTER_FAILED = "raster_failed"
    UNSUPPORTED_FORMAT = "unsupported_format"
    VARIANT_GENERATION_FAILED = "variant_generation_failed"
    SOURCE_NOT_FOUND = "source_not_found"


@dataclass(frozen=True)
class PreprocessingError:
    code: PreprocessingErrorCode
    detail: str
    """The real underlying message — an OpenCV/PyMuPDF exception's own text, not a
    paraphrase (`v3-plan-04-v2-audit-findings.md`'s `str(e)`-instead-of-traceback finding,
    applied here)."""


class PreprocessingInternalError(Exception):
    """Base for everything this package raises internally, never across its own boundary."""


class RasterFailed(PreprocessingInternalError):
    """PDF rendering or image decode genuinely failed — a corrupt file, a PDF library error,
    an OpenCV decode returning `None`."""


class UnsupportedFormat(PreprocessingInternalError):
    """The source file's format isn't one this API's raster path (§5.3) handles — not a PDF,
    not a standard OpenCV-decodable raster format, and not HEIC/HEIF either."""


class VariantGenerationFailed(PreprocessingInternalError):
    """One variant kind's own generator raised — an OpenCV operation failed on this specific
    image (e.g. `DESKEW`'s contour search finding no contours at all on a blank/near-uniform
    image)."""

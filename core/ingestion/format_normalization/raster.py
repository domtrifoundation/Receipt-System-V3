"""PDF rendering and image-format decode (deep-dive §4.1) — delegates to Preprocessing
API's own `raster.py` for the actual decode/render calls, so every `NormalizedImage` this
sub-API produces has exactly the same shape (BGR `numpy.ndarray` -> PNG bytes) as
Preprocessing's own rasterized output, regardless of which Ingestion source or which
sub-API produced it — Preprocessing never needs to know or care which channel an image
arrived through (deep-dive §4.1's own stated goal).

This module's own job on top of that reused decode step is **page enumeration**:
Preprocessing's `decode_image_bytes(data, page_index, scale)` decodes exactly one page at
a time (the right shape for its own single-page `RasterRequest`), while a multi-page PDF
arriving through Ingestion needs every page rasterized up front — this module counts pages
via a real `fitz.open()` call and loops.
"""

from __future__ import annotations

import asyncio

from .errors import RasterFailed, UnsupportedFormat

__all__ = ["DEFAULT_SCALE", "page_count", "rasterize_all_pages"]

#: Matches Preprocessing's own default render scale (`RasterRequest.scale`'s default) —
#: kept as a named constant here since this module calls `decode_image_bytes` directly
#: rather than through a `RasterRequest`, which would otherwise supply this itself.
DEFAULT_SCALE = 2.5


def page_count(data: bytes, fmt: str) -> int:
    """`1` for anything that isn't a multi-page container; a real PDF page count via
    `fitz.open()` otherwise."""
    if fmt != "pdf":
        return 1
    import fitz

    try:
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            return doc.page_count
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001 - a PDF that fails to even open is a raster failure
        raise RasterFailed(f"failed to open PDF for page counting: {exc}") from exc


async def rasterize_all_pages(data: bytes, *, scale: float = DEFAULT_SCALE) -> tuple[bytes, ...]:
    """Every page, PNG-encoded, in order. Raises `UnsupportedFormat`/`RasterFailed` (this
    sub-package's own taxonomy) — the caller (`service.py`'s own normalization pipeline)
    is where these become a per-image `IngestionError` on `contracts.NormalizedImage`,
    never a propagated exception across the parent API's own boundary."""
    from core.preprocessing.errors import RasterFailed as PreprocessingRasterFailed
    from core.preprocessing.errors import UnsupportedFormat as PreprocessingUnsupportedFormat
    from core.preprocessing.raster import decode_image_bytes, encode_image_png, sniff_format

    loop = asyncio.get_running_loop()
    try:
        fmt = await loop.run_in_executor(None, sniff_format, data)
    except PreprocessingUnsupportedFormat as exc:
        raise UnsupportedFormat(str(exc)) from exc

    count = await loop.run_in_executor(None, page_count, data, fmt)

    pages: list[bytes] = []
    for page_index in range(count):
        try:
            image = await loop.run_in_executor(None, decode_image_bytes, data, page_index, scale)
            encoded = await loop.run_in_executor(None, encode_image_png, image)
        except PreprocessingRasterFailed as exc:
            raise RasterFailed(str(exc)) from exc
        pages.append(encoded)
    return tuple(pages)

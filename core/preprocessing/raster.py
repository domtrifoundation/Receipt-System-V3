"""PDF/image ingestion → base raster image, adaptive re-render (deep-dive §5).

Owns what the OCR deep-dive left implicit (§1): every OCR engine receives an already-rasterized
`image_ref` and never touches PDF rendering itself — closing the real risk of N OCR engines each
independently re-rasterizing the same PDF page at slightly different scales as duplicated work.

**Format is sniffed from the actual bytes, never trusted from a filename or declared
extension** — the same posture Content Security already takes toward declared MIME types
(`docs/PRINCIPLES.md` §4.2): a `.jpg` that is actually a PDF, or vice versa, must not silently
take the wrong decode path.

Blocking I/O (PyMuPDF rendering, OpenCV decode) is dispatched via `run_in_executor` — this
module's own two entrypoints (`rasterize`, `rerender_at_scale`) are `async def` for that reason,
matching every other API's identical async-wraps-blocking-native-work convention in this
project.
"""

from __future__ import annotations

import asyncio

import cv2
import fitz
import numpy as np
import pillow_heif

from .contracts import BlobRef, BlobStoreGateway, RasterRequest, RasterResult
from .errors import PreprocessingError, PreprocessingErrorCode, RasterFailed, UnsupportedFormat

__all__ = [
    "decode_image_bytes",
    "encode_image_png",
    "rasterize",
    "rerender_at_scale",
    "sniff_format",
]

pillow_heif.register_heif_opener()

#: Real magic-byte prefixes, checked in order — never a filename/extension guess (§5.3's own
#: "OpenCV does not support HEIC out of the box" gap, made structural rather than left implicit).
_PDF_MAGIC = b"%PDF-"
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_BMP_MAGIC = b"BM"
_WEBP_MAGIC_RIFF = b"RIFF"
_WEBP_MAGIC_WEBP = b"WEBP"


def sniff_format(data: bytes) -> str:
    """Returns `"pdf"`, `"heic"`, or `"raster"` (anything OpenCV's own `imdecode` handles
    directly: JPEG/PNG/BMP/WebP) — real byte-signature detection, never extension-based.

    HEIC/HEIF containers are ISO base media format (the same family as MP4) — their signature
    lives a few bytes in (`ftyp` box) rather than at offset 0, unlike every other format checked
    here, which is exactly the kind of detail that is easy to get wrong reasoning about this in
    the abstract rather than checking real file structure.
    """
    if data.startswith(_PDF_MAGIC):
        return "pdf"
    if data.startswith(_JPEG_MAGIC) or data.startswith(_PNG_MAGIC) or data.startswith(_BMP_MAGIC):
        return "raster"
    if data[4:8] == b"ftyp" and (b"heic" in data[8:16] or b"heix" in data[8:16] or b"mif1" in data[8:16]):
        return "heic"
    if data.startswith(_WEBP_MAGIC_RIFF) and data[8:12] == _WEBP_MAGIC_WEBP:
        return "raster"
    raise UnsupportedFormat(f"unrecognized file signature (first 16 bytes: {data[:16]!r})")


def _render_pdf_page(data: bytes, page_index: int, scale: float) -> np.ndarray:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        # PyMuPDF's own pixmap is RGB(A); OpenCV's native channel order is BGR, not RGB — an
        # easy, real mistake to make (the same one the deep-dive's own §4.4 flags for channel
        # boosting), so the conversion is explicit here rather than assumed.
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception as exc:  # noqa: BLE001 - converted to this package's own error taxonomy
        raise RasterFailed(f"PDF render failed: {exc}") from exc


def _decode_raster(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RasterFailed("cv2.imdecode returned None — bytes did not decode as a valid image")
    return img


def _decode_heic(data: bytes) -> np.ndarray:
    try:
        from PIL import Image
        import io

        pil_image = Image.open(io.BytesIO(data)).convert("RGB")
        rgb = np.array(pil_image)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except Exception as exc:  # noqa: BLE001
        raise RasterFailed(f"HEIC decode failed: {exc}") from exc


def decode_image_bytes(data: bytes, page_index: int, scale: float) -> np.ndarray:
    """Sniffs `data`'s real format and decodes it to a BGR `numpy.ndarray` — public (not
    module-private) specifically because `generation.py`'s own `ProcessPoolExecutor` workers
    need this same decode step: §8.4's rule is "pass `image_ref` across the process boundary,
    never image bytes," so each worker re-reads and re-decodes the source itself rather than
    the parent process decoding once and pickling the result across."""
    fmt = sniff_format(data)
    if fmt == "pdf":
        return _render_pdf_page(data, page_index, scale)
    if fmt == "heic":
        return _decode_heic(data)
    return _decode_raster(data)


def encode_image_png(img: np.ndarray) -> bytes:
    """The inverse of `decode_image_bytes` — also public for the same cross-process reuse
    reason: a worker's own output has to be re-encoded to bytes before crossing back."""
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RasterFailed("cv2.imencode failed to encode the rasterized image")
    return buf.tobytes()


async def rasterize(request: RasterRequest, blob_store: BlobStoreGateway) -> RasterResult:
    """§5's own entrypoint. Never raises — a decode/render failure comes back as a
    `RasterResult` with `image_ref=None` and `.error` set (`docs/PRINCIPLES.md` §4.1)."""
    loop = asyncio.get_running_loop()
    try:
        source_bytes = await blob_store.read_blob(request.source_ref)
        img = await loop.run_in_executor(
            None, decode_image_bytes, source_bytes, request.page_index, request.scale
        )
        encoded = await loop.run_in_executor(None, encode_image_png, img)
        image_ref = await blob_store.write_blob(encoded)
    except UnsupportedFormat as exc:
        return RasterResult(
            image_ref=None, width=0, height=0, duration_ms=0, device="cpu",
            error=PreprocessingError(code=PreprocessingErrorCode.UNSUPPORTED_FORMAT, detail=str(exc)),
        )
    except RasterFailed as exc:
        return RasterResult(
            image_ref=None, width=0, height=0, duration_ms=0, device="cpu",
            error=PreprocessingError(code=PreprocessingErrorCode.RASTER_FAILED, detail=str(exc)),
        )

    height, width = img.shape[:2]
    return RasterResult(image_ref=image_ref, width=width, height=height, duration_ms=0, device="cpu")


async def rerender_at_scale(
    request: RasterRequest, blob_store: BlobStoreGateway, *, scale: float
) -> RasterResult:
    """§5.2's adaptive-scale retry primitive: a second `Rasterize`-shaped call at a higher
    `scale`, callable by whatever orchestrator decided a fast first pass wasn't good enough.

    Deliberately not different logic from `rasterize` itself — just `rasterize` called again
    with a different `scale`, centralized here so the retry decision lives in exactly one place
    rather than being duplicated per-caller (§5.2's own stated reasoning for why this moved
    into Preprocessing at all, rather than staying implicit inside each OCR engine).
    """
    from dataclasses import replace

    return await rasterize(replace(request, scale=scale), blob_store)

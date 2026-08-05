"""`raster.py` (`v3-deepdive-03-preprocessing-api.md` §5).

Format detection is tested against real magic bytes for every format this API claims to
handle, never against a filename — the whole point of `sniff_format` existing at all is that a
filename/extension is not trustworthy (`docs/PRINCIPLES.md` §4.2's posture, applied here).
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from core.preprocessing.contracts import RasterRequest
from core.preprocessing.errors import PreprocessingErrorCode, UnsupportedFormat
from core.preprocessing.raster import decode_image_bytes, encode_image_png, rasterize, rerender_at_scale, sniff_format

from .conftest import encode_jpeg_bytes, encode_png_bytes, make_solid_image, make_synthetic_pdf, run


def test_sniffs_a_real_pdf_by_its_actual_magic_bytes():
    assert sniff_format(make_synthetic_pdf()) == "pdf"


def test_sniffs_a_real_png_by_its_actual_magic_bytes():
    assert sniff_format(encode_png_bytes(make_solid_image())) == "raster"


def test_sniffs_a_real_jpeg_by_its_actual_magic_bytes():
    assert sniff_format(encode_jpeg_bytes(make_solid_image())) == "raster"


def test_an_unrecognized_byte_sequence_raises_unsupported_format_not_a_silent_guess():
    with pytest.raises(UnsupportedFormat):
        sniff_format(b"not a real file at all, just some bytes")


def test_a_filename_extension_is_never_consulted_only_real_bytes():
    """The entire reason this function exists: format is never trusted from how a caller named
    a file. A PDF's real bytes sniff as pdf even with no filename involved anywhere in the
    call — there is no extension parameter to this function at all, which is itself the test.
    """
    assert sniff_format(make_synthetic_pdf()) == "pdf"
    assert sniff_format(encode_png_bytes(make_solid_image())) == "raster"


def test_decode_image_bytes_renders_a_real_synthetic_pdf_page():
    data = make_synthetic_pdf(width=200, height=400)
    img = decode_image_bytes(data, page_index=0, scale=1.0)
    assert img.shape[0] > 0 and img.shape[1] > 0
    assert img.ndim == 3  # a real BGR render, not left as some other shape


def test_decode_image_bytes_scale_actually_changes_the_rendered_size():
    data = make_synthetic_pdf(width=200, height=400)
    small = decode_image_bytes(data, page_index=0, scale=1.0)
    large = decode_image_bytes(data, page_index=0, scale=2.0)
    assert large.shape[0] > small.shape[0]
    assert large.shape[1] > small.shape[1]


def test_decode_image_bytes_decodes_a_real_raster_image():
    original = make_solid_image(size=48)
    img = decode_image_bytes(encode_png_bytes(original), page_index=0, scale=1.0)
    assert img.shape[:2] == (48, 48)


def test_encode_image_png_round_trips_pixel_data():
    original = make_solid_image(size=16, color=(10, 20, 30))
    encoded = encode_image_png(original)
    decoded = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert np.array_equal(decoded, original)


# --- rasterize() / rerender_at_scale() -------------------------------------------------------


def test_rasterize_a_real_synthetic_pdf_end_to_end(blob_store):
    source_ref = run(blob_store.write_blob(make_synthetic_pdf()))
    request = RasterRequest(run_id="r1", user_id="u1", source_ref=source_ref)

    result = run(rasterize(request, blob_store))

    assert result.error is None
    assert result.image_ref is not None
    assert result.width > 0 and result.height > 0
    assert result.image_ref.logical_id in blob_store.blobs


def test_rasterize_a_real_raster_image_end_to_end(blob_store):
    source_ref = run(blob_store.write_blob(encode_png_bytes(make_solid_image(size=40))))
    request = RasterRequest(run_id="r1", user_id="u1", source_ref=source_ref)

    result = run(rasterize(request, blob_store))

    assert result.error is None
    assert (result.width, result.height) == (40, 40)


def test_rasterize_an_unsupported_format_returns_data_not_an_exception(blob_store):
    """Errors are data at this API's boundary (`docs/PRINCIPLES.md` §4.1) — a genuinely
    unreadable source file must come back as a `RasterResult` with `.error` set, never raise
    out of `rasterize` itself."""
    source_ref = run(blob_store.write_blob(b"garbage, not a real file"))
    request = RasterRequest(run_id="r1", user_id="u1", source_ref=source_ref)

    result = run(rasterize(request, blob_store))

    assert result.image_ref is None
    assert result.error is not None
    assert result.error.code is PreprocessingErrorCode.UNSUPPORTED_FORMAT


def test_rerender_at_scale_produces_a_larger_image_than_the_original_request(blob_store):
    """§5.2's adaptive-scale retry primitive — a second call at a higher scale, not different
    logic from a plain `rasterize`."""
    source_ref = run(blob_store.write_blob(make_synthetic_pdf(width=200, height=400)))
    request = RasterRequest(run_id="r1", user_id="u1", source_ref=source_ref, scale=1.0)

    first = run(rasterize(request, blob_store))
    retried = run(rerender_at_scale(request, blob_store, scale=3.0))

    assert retried.width > first.width
    assert retried.height > first.height
    # The original request's own scale is untouched by the retry — replace() builds a new
    # request rather than mutating the frozen one passed in.
    assert request.scale == 1.0

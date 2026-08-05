"""Format Normalization sub-API (`v3-deepdive-42-format-normalization.md`) — real
PyMuPDF/Pillow/`zipfile` calls, no mocking of the libraries themselves.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from core.ingestion.format_normalization.archive_extract import extract_entries, list_entries
from core.ingestion.format_normalization.codecs import encode_archival
from core.ingestion.format_normalization.errors import UnsupportedFormat
from core.ingestion.format_normalization.raster import page_count, rasterize_all_pages

from .conftest import make_synthetic_jpeg, make_synthetic_pdf, run


def test_page_count_for_a_multipage_pdf():
    pdf_bytes = make_synthetic_pdf(pages=3)
    assert page_count(pdf_bytes, "pdf") == 3


def test_page_count_is_one_for_non_pdf():
    assert page_count(b"irrelevant", "raster") == 1


def test_rasterize_all_pages_produces_one_png_per_page():
    pdf_bytes = make_synthetic_pdf(pages=3)
    pages = run(rasterize_all_pages(pdf_bytes))
    assert len(pages) == 3
    for page in pages:
        assert page[:8] == b"\x89PNG\r\n\x1a\n"


def test_rasterize_all_pages_handles_a_single_raster_image():
    jpeg_bytes = make_synthetic_jpeg()
    pages = run(rasterize_all_pages(jpeg_bytes))
    assert len(pages) == 1
    assert pages[0][:8] == b"\x89PNG\r\n\x1a\n"


def test_rasterize_all_pages_raises_for_unrecognized_bytes():
    with pytest.raises(UnsupportedFormat):
        run(rasterize_all_pages(b"not a real file at all"))


def test_encode_archival_produces_real_avif_bytes():
    jpeg_bytes = make_synthetic_jpeg()
    avif_bytes = run(encode_archival(jpeg_bytes, codec="avif", quality=75))
    assert avif_bytes[4:12] == b"ftypavif"


def test_encode_archival_produces_real_webp_bytes():
    jpeg_bytes = make_synthetic_jpeg()
    webp_bytes = run(encode_archival(jpeg_bytes, codec="webp", quality=75))
    assert webp_bytes[:4] == b"RIFF"
    assert webp_bytes[8:12] == b"WEBP"


def test_encode_archival_rejects_an_unknown_codec():
    with pytest.raises(UnsupportedFormat):
        run(encode_archival(make_synthetic_jpeg(), codec="jpeg2000"))


def test_zip_list_and_extract_entries_skip_directories():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("receipt1.jpg", b"data1")
        z.writestr("receipt2.jpg", b"data2")
        z.writestr("subdir/", "")
    zip_bytes = buf.getvalue()

    names = run(list_entries(zip_bytes))
    assert set(names) == {"receipt1.jpg", "receipt2.jpg"}

    entries = run(extract_entries(zip_bytes))
    by_name = {e.filename: e.data for e in entries}
    assert by_name == {"receipt1.jpg": b"data1", "receipt2.jpg": b"data2"}


def test_extract_entries_raises_for_a_bad_zip():
    from core.ingestion.format_normalization.errors import ArchiveExtractFailed

    with pytest.raises(ArchiveExtractFailed):
        run(list_entries(b"not a zip file"))

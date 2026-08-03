"""`IngestionServicer` and `normalize_source_file()` (deep-dive §6, Format Normalization
deep-dive §3) — the full pipeline against a real, in-process Content Security service
(not mocked) and real PyMuPDF/Pillow calls, exercising exactly the branches manually
verified live during development: a multi-page PDF (archival = original bytes stored
as-is, one base image per page) and a plain raster image (archival = real codec
re-encode).
"""

from __future__ import annotations

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.content_security.providers.base import ProviderRegistry  # noqa: E402
from core.content_security.service import serve as cs_serve  # noqa: E402
from core.ingestion.content_security_client import ContentSecurityClient  # noqa: E402
from core.ingestion.service import IngestionServicer, normalize_source_file  # noqa: E402

from .conftest import AlwaysCleanProvider, make_synthetic_jpeg, make_synthetic_pdf, run  # noqa: E402


@pytest.fixture
def clean_content_security_server():
    registry = ProviderRegistry()
    registry.register(AlwaysCleanProvider())
    server = cs_serve("127.0.0.1:19742", registry=registry)
    yield ContentSecurityClient("127.0.0.1:19742")
    server.stop(None)


@pytest.fixture
def rejecting_content_security_server():
    server = cs_serve("127.0.0.1:19743")  # no provider registered -> everything rejected
    yield ContentSecurityClient("127.0.0.1:19743")
    server.stop(None)


@pytest.mark.slow
def test_multipage_pdf_produces_one_image_per_page_and_stores_original_bytes_archivally(
    blob_store, clean_content_security_server
):
    from core.ingestion.contracts import SourceFile, SourceKind, BlobRef
    import asyncio

    pdf_bytes = make_synthetic_pdf(pages=2)
    raw_ref = asyncio.run(blob_store.write_blob(pdf_bytes))
    source_file = SourceFile(
        run_id="r1", user_id="u1", source=SourceKind.DIRECT_UPLOAD,
        raw_blob_ref=raw_ref, original_filename="receipt.pdf", declared_mime_type="application/pdf",
    )

    result = run(normalize_source_file(source_file, blob_store, clean_content_security_server))
    assert result.error is None
    assert len(result.images) == 2
    assert blob_store.blobs[result.archival_blob_ref.logical_id] == pdf_bytes


@pytest.mark.slow
def test_a_plain_image_is_archivally_re_encoded_not_stored_as_is(blob_store, clean_content_security_server):
    from core.ingestion.contracts import SourceFile, SourceKind
    import asyncio

    jpeg_bytes = make_synthetic_jpeg()
    raw_ref = asyncio.run(blob_store.write_blob(jpeg_bytes))
    source_file = SourceFile(
        run_id="r1", user_id="u1", source=SourceKind.DIRECT_UPLOAD,
        raw_blob_ref=raw_ref, original_filename="photo.jpg", declared_mime_type="image/jpeg",
    )

    result = run(normalize_source_file(source_file, blob_store, clean_content_security_server))
    assert result.error is None
    assert len(result.images) == 1
    archival_bytes = blob_store.blobs[result.archival_blob_ref.logical_id]
    assert archival_bytes != jpeg_bytes
    assert archival_bytes[4:12] == b"ftypavif"


@pytest.mark.slow
def test_content_security_rejection_produces_no_images(blob_store, rejecting_content_security_server):
    from core.ingestion.contracts import SourceFile, SourceKind
    import asyncio

    jpeg_bytes = make_synthetic_jpeg()
    raw_ref = asyncio.run(blob_store.write_blob(jpeg_bytes))
    source_file = SourceFile(
        run_id="r1", user_id="u1", source=SourceKind.DIRECT_UPLOAD,
        raw_blob_ref=raw_ref, original_filename="photo.jpg", declared_mime_type="image/jpeg",
    )

    result = run(normalize_source_file(source_file, blob_store, rejecting_content_security_server))
    assert result.error is not None
    assert result.error.code.value == "content_security_rejected"
    assert result.images == ()
    assert result.archival_blob_ref is None


@pytest.mark.slow
def test_submit_direct_upload_through_the_servicer_directly(blob_store, clean_content_security_server):
    from core.ingestion.generated import ingestion_pb2 as pb

    servicer = IngestionServicer(blob_store, content_security=clean_content_security_server)
    pdf_bytes = make_synthetic_pdf(pages=1)

    async def go():
        request = pb.DirectUploadRequest(
            run_id="r1", user_id="u1", filename="receipt.pdf",
            declared_mime_type="application/pdf", content=pdf_bytes,
        )
        return await servicer.SubmitDirectUpload(request)

    import asyncio

    response = asyncio.run(go())
    assert response.error_code == ""
    assert len(response.images) == 1


@pytest.mark.slow
def test_scan_session_lifecycle_through_the_servicer(blob_store, clean_content_security_server):
    from core.ingestion.generated import ingestion_pb2 as pb
    from .conftest import make_textured_strip
    import cv2
    import asyncio

    servicer = IngestionServicer(blob_store, content_security=clean_content_security_server)

    async def go():
        start_response = await servicer.StartScanSession(
            pb.StartScanRequest(run_id="r1", user_id="u1")
        )
        session_id = start_response.session_id

        ok, buf = cv2.imencode(".png", make_textured_strip(400, 300))
        frame_response = await servicer.SubmitScanFrame(
            pb.ScanFrameRequest(session_id=session_id, frame=buf.tobytes())
        )
        assert frame_response.error_code == ""
        assert frame_response.frame_index == 0

        return await servicer.FinalizeScanSession(pb.FinalizeScanRequest(session_id=session_id))

    response = asyncio.run(go())
    assert response.error_code == ""
    assert len(response.images) == 1


@pytest.mark.slow
def test_list_enabled_sources_reflects_the_real_registry(blob_store, clean_content_security_server):
    from core.ingestion.generated import ingestion_pb2 as pb
    import asyncio

    servicer = IngestionServicer(blob_store, content_security=clean_content_security_server)

    async def go():
        return await servicer.ListEnabledSources(pb.ListSourcesRequest())

    response = asyncio.run(go())
    assert "direct_upload" in response.available_sources

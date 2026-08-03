"""In-browser scanner's server-side half (deep-dive §4.3.2) — real `cv2.Stitcher` calls
against real synthetic overlapping frames, not mocked."""

from __future__ import annotations

import pytest

cv2 = pytest.importorskip("cv2", reason="opencv-python has no prebuilt wheel for this interpreter yet")

from core.ingestion.errors import StitchFailed  # noqa: E402
from core.ingestion.sources.scanner.capture_session import CaptureSessionStore  # noqa: E402
from core.ingestion.sources.scanner.stitcher import stitch_panorama  # noqa: E402

from .conftest import make_textured_strip, run  # noqa: E402


def test_stitch_panorama_succeeds_on_real_overlapping_frames():
    full = make_textured_strip()
    h, w = full.shape[:2]
    frame1 = full[:, 0 : int(w * 0.6)]
    frame2 = full[:, int(w * 0.4) :]
    result = run(stitch_panorama((frame1, frame2)))
    assert result.shape[0] == h
    assert result.shape[1] > frame1.shape[1]  # wider than either input frame alone


def test_stitch_panorama_requires_at_least_two_frames():
    frame = make_textured_strip()
    with pytest.raises(StitchFailed):
        run(stitch_panorama((frame,)))


def test_stitch_panorama_reports_the_real_status_code_on_failure():
    import numpy as np

    blank1 = np.zeros((100, 100, 3), dtype=np.uint8)
    blank2 = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(StitchFailed) as excinfo:
        run(stitch_panorama((blank1, blank2)))
    assert excinfo.value.status_code != 0


def test_capture_session_single_frame_finalize(blob_store):
    store = CaptureSessionStore()
    session = store.start("r1", "u1")
    ok, buf = cv2.imencode(".png", make_textured_strip(400, 300))
    store.submit_frame(session.session_id, buf.tobytes())
    result = run(store.finalize(session.session_id, blob_store))
    assert result.source.value == "scanner"
    assert blob_store.blobs[result.raw_blob_ref.logical_id][:8] == b"\x89PNG\r\n\x1a\n"
    assert store.get(session.session_id) is None


def test_capture_session_multi_frame_finalize_stitches(blob_store):
    store = CaptureSessionStore()
    session = store.start("r2", "u2")
    full = make_textured_strip()
    h, w = full.shape[:2]
    frame1 = full[:, 0 : int(w * 0.6)]
    frame2 = full[:, int(w * 0.4) :]
    for frame in (frame1, frame2):
        ok, buf = cv2.imencode(".png", frame)
        store.submit_frame(session.session_id, buf.tobytes())
    result = run(store.finalize(session.session_id, blob_store))
    stitched_bytes = blob_store.blobs[result.raw_blob_ref.logical_id]
    assert stitched_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_capture_session_finalize_with_no_frames_raises(blob_store):
    store = CaptureSessionStore()
    session = store.start("r3", "u3")
    with pytest.raises(StitchFailed):
        run(store.finalize(session.session_id, blob_store))


def test_capture_session_unknown_session_raises_key_error(blob_store):
    store = CaptureSessionStore()
    with pytest.raises(KeyError):
        run(store.finalize("does-not-exist", blob_store))

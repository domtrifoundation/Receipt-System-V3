"""Shared fixtures for Preprocessing's unit tests.

Every fixture here is synthetic — small in-memory images and a synthetic PDF built with
PyMuPDF's own drawing API — never a real receipt image, matching this deep-dive's own §11:
"each variant generator tested against small synthetic images... mocked/synthetic, no real
receipt images needed for unit-level correctness checks." Real-receipt validation is a
separate, manual, bench-shaped activity, not something this automated suite depends on.

`run()` exists instead of `pytest-asyncio` for the same reason every other package's own
conftest gives: this repo does not carry that dependency.

`nox -s forward_compat` deliberately installs a narrow dependency set, and `opencv-python`/
`pymupdf` do not yet have prebuilt wheels for 3.15 (still a beta release as of this writing) —
confirmed directly (`pip index versions numpy` resolves fine; installing against this
interpreter falls through to a from-source build and fails on an unrelated linker issue,
meaning no compatible wheel was found at all). None of this package's own tests are
`forward_compat`-marked, so the fix is the same guard `core/auth/`'s and `core/account_guardian/`'s
own servicer tests already carry for the equivalent `grpcio` gap: skip cleanly at *collection*
time rather than let a bare top-level import abort the whole session.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2", reason="opencv-python has no prebuilt wheel for this interpreter yet")
fitz = pytest.importorskip("fitz", reason="pymupdf has no prebuilt wheel for this interpreter yet")
np = pytest.importorskip("numpy", reason="numpy has no prebuilt wheel for this interpreter yet")

from core.preprocessing.contracts import BlobRef  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@dataclass
class FakeBlobStore:
    """An in-memory `BlobStoreGateway` — real enough to prove `raster.py`/`generation.py`'s
    own read/write call shape, without needing a real Persistence connection."""

    blobs: dict[str, bytes] = field(default_factory=dict)

    async def read_blob(self, ref: BlobRef) -> bytes:
        return self.blobs[ref.logical_id]

    async def write_blob(self, data: bytes) -> BlobRef:
        logical_id = str(uuid.uuid4())
        self.blobs[logical_id] = data
        return BlobRef(logical_id=logical_id)


@pytest.fixture
def blob_store() -> FakeBlobStore:
    return FakeBlobStore()


def make_checkerboard(size: int = 64, square: int = 8) -> np.ndarray:
    """A synthetic BGR checkerboard — high-contrast, known structure, good for confirming
    `BW_THRESHOLD`'s Otsu output actually binarizes at a sane split (deep-dive §11's own
    example)."""
    board = np.zeros((size, size), dtype=np.uint8)
    for y in range(0, size, square):
        for x in range(0, size, square):
            if ((x // square) + (y // square)) % 2 == 0:
                board[y : y + square, x : x + square] = 255
    return cv2.cvtColor(board, cv2.COLOR_GRAY2BGR)


def make_solid_image(size: int = 32, color: tuple[int, int, int] = (120, 140, 160)) -> np.ndarray:
    """A plain solid-color BGR image — no structure at all, useful for pinning degenerate-input
    behaviour (e.g. `DESKEW` finding no contour on a genuinely uniform image)."""
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:, :] = color
    return img


def encode_png_bytes(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    assert ok
    return buf.tobytes()


def encode_jpeg_bytes(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", image)
    assert ok
    return buf.tobytes()


def make_synthetic_pdf(text: str = "TEST RECEIPT", width: int = 200, height: int = 400) -> bytes:
    """A genuine, minimal, one-page PDF built with PyMuPDF's own drawing API — real PDF bytes
    with a real text layer and a real rectangle, not a hand-crafted byte string. Good enough to
    exercise `raster.py`'s own PDF-rendering path end to end without touching a real receipt.
    """
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(10, 10, width - 10, height - 10))
    page.insert_text((20, 30), text)
    data = doc.tobytes()
    doc.close()
    return data


def make_rotated(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    """Rotates a synthetic test image by a known angle — used to confirm `DESKEW` recovers a
    known skew within tolerance (deep-dive §11's own named bench-shaped test, done here at
    unit scale against a synthetic image rather than a real photo)."""
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle_degrees, 1.0)
    return cv2.warpAffine(image, matrix, (w, h), borderMode=cv2.BORDER_REPLICATE)

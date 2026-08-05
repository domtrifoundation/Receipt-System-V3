"""`TesseractEngine` (deep-dive §4.2) — real subprocess calls against the actual system
`tesseract` binary, not mocked. Skips cleanly if no binary is discoverable on this machine
(`docs/PRINCIPLES.md` §4.4's graceful-degradation posture applied to test collection
itself, not just runtime) — the same reasoning `core/auth`'s `grpcio` guard follows,
generalized to a system binary rather than a pip package.
"""

from __future__ import annotations

import shutil

import pytest

from core.ocr.engines.tesseract_engine import TesseractConfig, TesseractEngine

from .conftest import make_text_png, run


def _discover_tesseract() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    import os

    windows_default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.name == "nt" and os.path.exists(windows_default):
        return windows_default
    return None


_BINARY_PATH = _discover_tesseract()
pytestmark = pytest.mark.skipif(
    _BINARY_PATH is None, reason="no tesseract binary discoverable on this machine"
)


@pytest.mark.slow
def test_is_available_against_the_real_binary():
    engine = TesseractEngine(TesseractConfig(binary_path=_BINARY_PATH))
    assert run(engine.is_available()) is True


@pytest.mark.slow
def test_reads_real_rendered_text():
    engine = TesseractEngine(TesseractConfig(binary_path=_BINARY_PATH, psm=7))
    image = make_text_png("HELLO RECEIPT")
    reading = run(engine.read(image))
    assert reading.error is None
    assert "HELLO" in reading.text.upper() or "RECEIPT" in reading.text.upper()


@pytest.mark.slow
def test_unavailable_binary_path_reports_unavailable():
    engine = TesseractEngine(TesseractConfig(binary_path="this-binary-does-not-exist"))
    assert run(engine.is_available()) is False

"""`WindowsOcrEngine` (deep-dive §4.5) — real `Windows.Media.Ocr` calls via `winsdk` on a
real Windows machine, or a confirmed structural-unavailability check everywhere else.
Skips the read-path assertions on non-Windows rather than the whole module, since the
platform gate itself (`OcrEnginePlatformUnsupported`) is exactly what should be exercised
for real on every other platform — not skipped away.
"""

from __future__ import annotations

import platform

import pytest

from core.ocr.engines.windows_ocr_engine import WindowsOcrEngine
from core.ocr.errors import OcrEnginePlatformUnsupported

from .conftest import make_text_png, run

_IS_WINDOWS = platform.system() == "Windows"


def test_is_available_matches_this_machines_actual_platform():
    engine = WindowsOcrEngine()
    available = run(engine.is_available())
    if not _IS_WINDOWS:
        assert available is False


def test_read_on_non_windows_raises_platform_unsupported():
    if _IS_WINDOWS:
        pytest.skip("this machine is Windows — the unsupported path is not this machine's own state")
    engine = WindowsOcrEngine()
    with pytest.raises(OcrEnginePlatformUnsupported):
        run(engine.read(b"irrelevant"))


@pytest.mark.slow
@pytest.mark.skipif(not _IS_WINDOWS, reason="Windows.Media.Ocr only exists on Windows")
def test_reads_real_rendered_text_on_windows():
    engine = WindowsOcrEngine()
    assert run(engine.is_available()) is True
    image = make_text_png("HELLO RECEIPT")
    reading = run(engine.read(image))
    assert reading.error is None
    assert reading.mean_confidence is None  # deep-dive §4.5: no confidence signal at all
    assert reading.regions == ()  # deliberately plain-text-only, see the module's own docstring

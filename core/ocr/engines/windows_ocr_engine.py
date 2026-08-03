"""Tier 2 — Windows OCR (deep-dive §4.5).

Wraps the OS-native `Windows.Media.Ocr` WinRT API via `winsdk` — the same engine behind
Snipping Tool's "Text Actions" and PowerToys' Text Extractor. Free, offline, genuinely
accurate on real-world photos, and **structurally absent on non-Windows platforms** — a
different failure category from a missing pip package (`OcrEnginePlatformUnsupported`,
not `OcrEngineUnavailable`), so the Interface API can show "not available on this OS"
rather than "not installed, run pip install" (deep-dive §4.5).

Confirmed live against a real receipt: `winsdk`'s WinRT bridge genuinely runs `asyncio`'s
own event loop (no separate COM message pump needed), and `DataWriter.write_bytes` needs
real `bytes`, not a `list[int]` — an easy mistake, since some other WinRT buffer-writing
APIs do want a list.

**Regions stay empty on purpose, not because `Windows.Media.Ocr` lacks word-level boxes —
it doesn't.** The deep-dive's own §4.3 decision draws the region-output line at "Windows
OCR is plain-text-only by nature," alongside the cloud tier and tier-0 text-layer
extraction; matching that classification here rather than the underlying API's actual
capability keeps a "does this engine populate `regions`" answer consistent with the
documented design instead of an accident of what the OS bridge happens to expose. The same
reasoning applies to confidence: WinRT's `OcrResult` carries no per-line or per-word score
at all, so `mean_confidence` is genuinely `None` here, not a design choice this adapter
made — `contracts.py`'s own docstring names Windows OCR as the example of this case.
"""

from __future__ import annotations

import platform
import time

from ..contracts import EngineName, EngineReading
from ..errors import OcrEngineCrashed, OcrEnginePlatformUnsupported, OcrEngineUnavailable
from .base import timed_reading

__all__ = ["WindowsOcrEngine"]


def _is_windows() -> bool:
    return platform.system() == "Windows"


class WindowsOcrEngine:
    @property
    def engine(self) -> EngineName:
        return EngineName.WINDOWS_OCR

    async def is_available(self) -> bool:
        if not _is_windows():
            return False
        try:
            from winsdk.windows.media.ocr import OcrEngine as WinOcrEngine  # noqa: PLC0415
        except ImportError:
            return False
        try:
            return WinOcrEngine.try_create_from_user_profile_languages() is not None
        except Exception:  # noqa: BLE001 - any probe failure means unavailable
            return False

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        if not _is_windows():
            raise OcrEnginePlatformUnsupported("Windows OCR is only available on Windows")

        try:
            from winsdk.windows.graphics.imaging import BitmapDecoder  # noqa: PLC0415
            from winsdk.windows.media.ocr import OcrEngine as WinOcrEngine  # noqa: PLC0415
            from winsdk.windows.storage.streams import (  # noqa: PLC0415
                DataWriter,
                InMemoryRandomAccessStream,
            )
        except ImportError as exc:
            raise OcrEngineUnavailable(str(exc)) from exc

        engine = WinOcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise OcrEngineUnavailable(
                "no OCR language pack installed — install one in Windows Settings"
            )

        try:
            stream = InMemoryRandomAccessStream()
            writer = DataWriter(stream)
            writer.write_bytes(image_bytes)
            await writer.store_async()
            await writer.flush_async()
            stream.seek(0)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            result = await engine.recognize_async(bitmap)
        except Exception as exc:  # noqa: BLE001 - a corrupt/undecodable image is a crash
            raise OcrEngineCrashed(f"{type(exc).__name__}: {exc}") from exc

        return timed_reading(start, self.engine, result.text or "", mean_confidence=None)

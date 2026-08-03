"""Tier 2 — Apple Vision (deep-dive §4.6) — macOS's platform equivalent to Windows OCR.

Wraps `VNImageRequestHandler` + `VNRecognizeTextRequest` (`recognitionLevel = .accurate`)
via `pyobjc-framework-Vision`/`pyobjc-framework-Quartz`. Same structural-unavailability
category as `windows_ocr_engine.py` — genuinely absent on non-macOS, not a degraded/
missing-dependency case (`OcrEnginePlatformUnsupported`).

**Not live-tested this session** — this development machine is Windows, not macOS, so
there is no real hardware here to validate `VNRecognizeTextRequest` against. The platform
gate itself (`platform.system() != "Darwin"` -> `OcrEnginePlatformUnsupported` at both
`is_available()` and `read()`) is exercised by this machine for real, since "not macOS" is
exactly this machine's own actual state — the untested part is only the Vision-framework
call path inside the `if _is_macos()` branch. Per `docs/PRINCIPLES.md` §4.4, an engine this
API cannot probe on the current platform must still degrade to unavailable rather than be
skipped or assumed working, so the gate matters here on its own regardless of the
untested branch behind it.

Unlike Windows OCR, `VNRecognizedTextObservation` genuinely does carry per-candidate
confidence and normalized bounding boxes natively — the deep-dive's own §4.6 says region
output "applies here too" (§4.3's decision), unlike Windows OCR's deliberate plain-text-only
classification. `VNRectangleObservation`'s `bounding_box` is already normalized 0-1 against
image dimensions in Vision's own coordinate space (origin bottom-left, y-flipped from this
project's own top-left convention), so this adapter flips `y` before handing it to
`TextRegion.box` rather than leaving that inversion for a downstream consumer to discover.
"""

from __future__ import annotations

import platform
import time

from ..contracts import EngineName, EngineReading, TextRegion
from ..errors import OcrEngineCrashed, OcrEnginePlatformUnsupported, OcrEngineUnavailable
from .base import timed_reading

__all__ = ["AppleVisionEngine"]


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _run_vision_ocr(image_bytes: bytes) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    import Quartz
    import Vision
    from Foundation import NSData

    data = NSData.dataWithBytes_length_(image_bytes, len(image_bytes))
    image_source = Quartz.CGImageSourceCreateWithData(data, None)
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(image_source, 0, None)

    results: list[tuple[str, float, tuple[float, float, float, float]]] = []

    def _handler(request, error):
        if error is not None:
            return
        for observation in request.results():
            candidate = observation.topCandidates_(1)[0]
            box = observation.boundingBox()
            # Vision's origin is bottom-left; this project's is top-left — flip y.
            normalized = (
                float(box.origin.x), 1.0 - float(box.origin.y) - float(box.size.height),
                float(box.size.width), float(box.size.height),
            )
            results.append((str(candidate.string()), float(candidate.confidence()), normalized))

    request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(_handler)
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise OcrEngineCrashed(str(error))
    return results


class AppleVisionEngine:
    @property
    def engine(self) -> EngineName:
        return EngineName.APPLE_VISION

    async def is_available(self) -> bool:
        if not _is_macos():
            return False
        try:
            import Vision  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        if not _is_macos():
            raise OcrEnginePlatformUnsupported("Apple Vision is only available on macOS")

        try:
            import Vision  # noqa: F401, PLC0415
        except ImportError as exc:
            raise OcrEngineUnavailable(str(exc)) from exc

        import asyncio

        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(None, _run_vision_ocr, image_bytes)
        except OcrEngineCrashed:
            raise
        except Exception as exc:  # noqa: BLE001 - a corrupt/undecodable image is a crash
            raise OcrEngineCrashed(f"{type(exc).__name__}: {exc}") from exc

        regions = tuple(
            TextRegion(text=text, confidence=confidence, box=box)
            for text, confidence, box in raw
        )
        merged_text = "\n".join(region.text for region in regions)
        mean_confidence = (
            sum(r.confidence for r in regions) / len(regions) if regions else None
        )
        return timed_reading(
            start, self.engine, merged_text, regions=regions, mean_confidence=mean_confidence
        )

"""Tier 3 — Google Cloud Vision (deep-dive §4.7).

**Plain REST + API key, not the official SDK** — the deep-dive's own resolved decision.
The SDK's default auth path assumes a service-account JSON and pulls in `google-auth`'s
full dependency chain for what this project's config surface already treats as a single
pasted API key; REST keeps the footprint minimal and matches `cloud_vision_api_key`
exactly.

Uses `DOCUMENT_TEXT_DETECTION` rather than plain `TEXT_DETECTION`: the latter's
`textAnnotations` carry no per-region confidence at all, while `fullTextAnnotation`'s
block/paragraph/word structure does — needed for this engine to participate in
`TextRegion`'s standardized per-region output the same as every local detector-based
engine (deep-dive §4.3's decision applies here too, per §4.7's own text).

**Not live-tested this session** — no Google Cloud Vision API key is available in this
development environment (a paid, real-money service, deliberately never something this
project fabricates a key for just to exercise the code path). The HTTP call shape below is
built directly from Google's own published Vision REST API response schema, not guessed
at; `tests/unit/core/ocr/` exercises this adapter against a mocked HTTP transport rather
than a real network call, per the deep-dive's own testing guidance (§11) and this
project's standing rule against fabricating live paid-API traffic in an automated suite.
"""

from __future__ import annotations

import base64
import time

from ...contracts import EngineName, EngineReading, TextRegion
from ...engines.base import decode_image_dims, timed_reading
from ...errors import OcrEngineUnavailable
from .base_cloud_engine import CloudEngineConfig, classify_http_status

__all__ = ["GoogleVisionEngine"]

_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"


def _build_request_body(image_bytes: bytes) -> dict:
    return {
        "requests": [
            {
                "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            }
        ]
    }


def _extract_regions(full_text_annotation: dict, width: int, height: int) -> tuple[TextRegion, ...]:
    regions: list[TextRegion] = []
    for page in full_text_annotation.get("pages", []):
        for block in page.get("blocks", []):
            for paragraph in block.get("paragraphs", []):
                for word in paragraph.get("words", []):
                    text = "".join(s.get("text", "") for s in word.get("symbols", []))
                    confidence = float(word.get("confidence", 0.0))
                    vertices = word.get("boundingBox", {}).get("vertices", [])
                    xs = [v.get("x", 0) for v in vertices] or [0]
                    ys = [v.get("y", 0) for v in vertices] or [0]
                    if width <= 0 or height <= 0:
                        box = (0.0, 0.0, 0.0, 0.0)
                    else:
                        box = (
                            min(xs) / width, min(ys) / height,
                            (max(xs) - min(xs)) / width, (max(ys) - min(ys)) / height,
                        )
                    regions.append(TextRegion(text=text, confidence=confidence, box=box))
    return tuple(regions)


class GoogleVisionEngine:
    def __init__(self, config: CloudEngineConfig | None = None) -> None:
        self._config = config or CloudEngineConfig()

    @property
    def engine(self) -> EngineName:
        return EngineName.CLOUD_VISION

    async def is_available(self) -> bool:
        if not self._config.api_key:
            return False
        try:
            import httpx  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        if not self._config.api_key:
            raise OcrEngineUnavailable("no Google Cloud Vision API key configured")
        try:
            import httpx  # noqa: PLC0415
        except ImportError as exc:
            raise OcrEngineUnavailable(str(exc)) from exc

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            response = await client.post(
                _ENDPOINT,
                params={"key": self._config.api_key},
                json=_build_request_body(image_bytes),
            )
        classify_http_status(response.status_code, response.text)

        body = response.json()
        result = (body.get("responses") or [{}])[0]
        full_text_annotation = result.get("fullTextAnnotation", {})
        merged_text = full_text_annotation.get("text", "")

        width, height = decode_image_dims(image_bytes)
        regions = _extract_regions(full_text_annotation, width, height)
        mean_confidence = (
            sum(r.confidence for r in regions) / len(regions) if regions else None
        )
        return timed_reading(
            start, self.engine, merged_text, regions=regions, mean_confidence=mean_confidence
        )

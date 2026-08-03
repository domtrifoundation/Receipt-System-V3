"""Tier 3 — Azure Document Intelligence (deep-dive §4.7), formerly Form Recognizer.

REST + API key, same reasoning as Google Cloud Vision. Uses the `prebuilt-read` model —
deliberately not `prebuilt-receipt`: Azure's receipt-specific model attempts field-level
extraction (vendor/total/date) as part of its own response, and that structured output is
explicitly out of scope for OCR API to consume (§1 — field extraction is Matching/
Inference territory). `prebuilt-read` gives back the same shape every other engine here
does: raw text plus per-word confidence and bounding polygons, nothing else.

Azure's Document Intelligence API is asynchronous by design: the initial `analyze` POST
returns `202 Accepted` with an `Operation-Location` header, and the actual result is
fetched by polling that URL until `status` leaves `"running"`. This adapter's own
`timeout_seconds` budgets the *whole* poll loop, not just the initial POST.

**Not live-tested this session** — no Azure Document Intelligence key/endpoint is
available in this environment (paid, real-money service). Built directly from Microsoft's
published REST API v4 (`analyzeResult.content`, `pages[].words[].confidence`) rather than
guessed at; exercised in `tests/unit/core/ocr/` against a mocked HTTP transport.
"""

from __future__ import annotations

import asyncio
import time

from ...contracts import EngineName, EngineReading, TextRegion
from ...errors import OcrEngineTimeout, OcrEngineUnavailable
from .base_cloud_engine import CloudEngineConfig, classify_http_status

__all__ = ["AzureDocumentIntelligenceEngine"]

_API_VERSION = "2024-11-30"
_MODEL = "prebuilt-read"
_POLL_INTERVAL_SECONDS = 1.0


def _extract_regions(analyze_result: dict) -> tuple[TextRegion, ...]:
    regions: list[TextRegion] = []
    for page in analyze_result.get("pages", []):
        page_width = page.get("width", 0) or 1
        page_height = page.get("height", 0) or 1
        for word in page.get("words", []):
            polygon = word.get("polygon", [])
            xs = polygon[0::2] or [0]
            ys = polygon[1::2] or [0]
            box = (
                min(xs) / page_width, min(ys) / page_height,
                (max(xs) - min(xs)) / page_width, (max(ys) - min(ys)) / page_height,
            )
            regions.append(
                TextRegion(
                    text=word.get("content", ""),
                    confidence=float(word.get("confidence", 0.0)),
                    box=box,
                )
            )
    return tuple(regions)


class AzureDocumentIntelligenceEngine:
    def __init__(self, config: CloudEngineConfig | None = None) -> None:
        self._config = config or CloudEngineConfig()

    @property
    def engine(self) -> EngineName:
        return EngineName.AZURE_DOCUMENT_INTELLIGENCE

    async def is_available(self) -> bool:
        if not (self._config.api_key and self._config.endpoint):
            return False
        try:
            import httpx  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        if not (self._config.api_key and self._config.endpoint):
            raise OcrEngineUnavailable("no Azure Document Intelligence key/endpoint configured")
        try:
            import httpx  # noqa: PLC0415
        except ImportError as exc:
            raise OcrEngineUnavailable(str(exc)) from exc

        analyze_url = (
            f"{self._config.endpoint.rstrip('/')}/documentintelligence/documentModels/"
            f"{_MODEL}:analyze?api-version={_API_VERSION}"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": self._config.api_key,
            "Content-Type": "application/octet-stream",
        }

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            submit = await client.post(analyze_url, headers=headers, content=image_bytes)
            classify_http_status(submit.status_code, submit.text)
            operation_url = submit.headers.get("Operation-Location", "")
            if not operation_url:
                raise OcrEngineUnavailable("Azure response carried no Operation-Location header")

            deadline = time.monotonic() + self._config.timeout_seconds
            analyze_result: dict = {}
            while True:
                if time.monotonic() > deadline:
                    raise OcrEngineTimeout(
                        f"Azure analysis did not complete within {self._config.timeout_seconds}s"
                    )
                poll = await client.get(
                    operation_url, headers={"Ocp-Apim-Subscription-Key": self._config.api_key}
                )
                classify_http_status(poll.status_code, poll.text)
                body = poll.json()
                status = body.get("status", "")
                if status == "succeeded":
                    analyze_result = body.get("analyzeResult", {})
                    break
                if status == "failed":
                    raise OcrEngineUnavailable(f"Azure analysis failed: {body}")
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)

        merged_text = analyze_result.get("content", "")
        regions = _extract_regions(analyze_result)
        mean_confidence = (
            sum(r.confidence for r in regions) / len(regions) if regions else None
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return EngineReading(
            engine=self.engine, text=merged_text, duration_ms=duration_ms,
            regions=regions, mean_confidence=mean_confidence,
        )

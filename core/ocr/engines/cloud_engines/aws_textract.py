"""Tier 3 — AWS Textract (deep-dive §4.7).

REST via `boto3` — AWS's own SDK is the practical choice here, unlike Google's, since it's
a lighter, more general-purpose dependency this project may already need elsewhere (e.g. an
S3-compatible blob backup target in the Persistence API design). Uses `detect_document_text`
(plain OCR), not `analyze_expense` — Textract's structured expense-field extraction is the
same out-of-scope category as Azure's `prebuilt-receipt` model (§1, §4.7).

`boto3` is a blocking, synchronous SDK — its own network calls happen inside regular
Python calls, not `asyncio`, so this adapter dispatches through `loop.run_in_executor`
rather than `await`ing a native coroutine, same pattern as the local-engine adapters
(`docs/PRINCIPLES.md`/deep-dive §10.1).

Textract's own `Geometry.BoundingBox` is already normalized 0-1 against image dimensions
(`Width`/`Height`/`Left`/`Top`) — unlike Google Vision's and Azure's pixel-space polygons,
no image-dimension decode is needed here to build `TextRegion.box`.

**Not live-tested this session** — no AWS credentials are configured in this environment
(paid, real-money service), and `boto3` itself is not installed in this session's `.venv`
(confirmed: `import boto3` raises `ModuleNotFoundError` here), so `is_available()` reports
`False` on this machine today — a real, live-confirmed degrade-to-unavailable outcome,
which is itself the graceful-degradation path this adapter exists to prove works
(`docs/PRINCIPLES.md` §4.4), not a gap in what got tested. Built directly from boto3's
published Textract `detect_document_text` response schema; exercised in
`tests/unit/core/ocr/` against a mocked client.
"""

from __future__ import annotations

import asyncio
import time

from ...contracts import EngineName, EngineReading, TextRegion
from ...errors import OcrAuthError, OcrEngineCrashed, OcrEngineUnavailable
from .base_cloud_engine import CloudEngineConfig

__all__ = ["AwsTextractEngine"]


def _run_textract(image_bytes: bytes, config: CloudEngineConfig) -> dict:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client(
        "textract",
        aws_access_key_id=config.extra.get("access_key_id") or None,
        aws_secret_access_key=config.extra.get("secret_access_key") or None,
        region_name=config.extra.get("region") or None,
    )
    try:
        return client.detect_document_text(Document={"Bytes": image_bytes})
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("UnrecognizedClientException", "AccessDeniedException"):
            raise OcrAuthError(str(exc)) from exc
        raise OcrEngineCrashed(str(exc)) from exc
    except BotoCoreError as exc:
        raise OcrEngineCrashed(str(exc)) from exc


def _extract(response: dict) -> tuple[str, tuple[TextRegion, ...]]:
    lines: list[str] = []
    regions: list[TextRegion] = []
    for block in response.get("Blocks", []):
        if block.get("BlockType") == "LINE":
            lines.append(block.get("Text", ""))
        elif block.get("BlockType") == "WORD":
            geometry = block.get("Geometry", {}).get("BoundingBox", {})
            box = (
                geometry.get("Left", 0.0), geometry.get("Top", 0.0),
                geometry.get("Width", 0.0), geometry.get("Height", 0.0),
            )
            regions.append(
                TextRegion(
                    text=block.get("Text", ""),
                    confidence=float(block.get("Confidence", 0.0)) / 100.0,
                    box=box,
                )
            )
    return ("\n".join(lines), tuple(regions))


class AwsTextractEngine:
    def __init__(self, config: CloudEngineConfig | None = None) -> None:
        self._config = config or CloudEngineConfig()

    @property
    def engine(self) -> EngineName:
        return EngineName.AWS_TEXTRACT

    async def is_available(self) -> bool:
        if not (self._config.extra.get("access_key_id") and self._config.extra.get("region")):
            return False
        try:
            import boto3  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        if not (self._config.extra.get("access_key_id") and self._config.extra.get("region")):
            raise OcrEngineUnavailable("no AWS credentials/region configured")
        try:
            import boto3  # noqa: F401, PLC0415
        except ImportError as exc:
            raise OcrEngineUnavailable(str(exc)) from exc

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _run_textract, image_bytes, self._config)

        merged_text, regions = _extract(response)
        mean_confidence = (
            sum(r.confidence for r in regions) / len(regions) if regions else None
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return EngineReading(
            engine=self.engine, text=merged_text, duration_ms=duration_ms,
            regions=regions, mean_confidence=mean_confidence,
        )

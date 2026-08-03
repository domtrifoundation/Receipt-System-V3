"""OCR API data contracts (`v3-deepdive-01-ocr-api.md` §3).

This is the only module in this package other APIs import from. It holds types and no
logic beyond trivially-derived predicates on a value's own fields.

`EngineReading` is present **once per requested engine, always, even on failure**
(`error` set, `text=""`) — the deep-dive's own §3 design choice, generalizing the V2
postmortem's "full traceback vs. `str(e)`" lesson to "never silently drop a requested unit
of work." A caller must be able to see "PaddleOCR was asked and crashed" as distinct from
"PaddleOCR wasn't asked."

`BlobRef` is re-declared here rather than imported from `core.persistence.contracts`, unlike
Preprocessing API's own choice to import it directly. The difference is deliberate: this
package's own `BlobStoreGateway` Protocol (below) only ever needs `.logical_id` to resolve a
blob, so pinning the exact Persistence type here would be a coupling this package doesn't
actually need to carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class EngineName(str, Enum):
    """Field-only-append discipline, same as the `.proto`. Existing values are never
    renamed or removed once shipped."""

    TEXT_LAYER = "text_layer"  # not OCR at all — PDF's embedded text, tier 0
    TESSERACT = "tesseract"
    RAPIDOCR = "rapidocr"
    PADDLEOCR = "paddleocr"
    WINDOWS_OCR = "windows_ocr"
    APPLE_VISION = "apple_vision"
    CLOUD_VISION = "cloud_vision"
    AZURE_DOCUMENT_INTELLIGENCE = "azure_document_intelligence"
    AWS_TEXTRACT = "aws_textract"


class AgreementLevel(str, Enum):
    UNANIMOUS = "unanimous"
    MAJORITY = "majority"
    SPLIT = "split"
    SINGLE_SOURCE = "single_source"
    NONE = "none"


class OcrErrorCode(str, Enum):
    """Wire-facing classification. Engine adapters raise the matching internal exception
    from `errors.py`; the registry catches it and produces this code — never a raw
    exception crossing this API's own boundary."""

    ENGINE_UNAVAILABLE = "engine_unavailable"
    ENGINE_PLATFORM_UNSUPPORTED = "engine_platform_unsupported"
    ENGINE_CRASHED = "engine_crashed"
    ENGINE_TIMEOUT = "engine_timeout"
    BUDGET_EXCEEDED = "budget_exceeded"
    NETWORK_ERROR = "network_error"
    AUTH_ERROR = "auth_error"
    RATE_LIMITED = "rate_limited"
    BLOB_NOT_FOUND = "blob_not_found"


@dataclass(frozen=True)
class OcrError:
    code: OcrErrorCode
    detail: str = ""


@dataclass(frozen=True)
class BlobRef:
    logical_id: str


@dataclass(frozen=True)
class TextRegion:
    text: str
    confidence: float  # engine's own per-region score, 0.0-1.0
    box: tuple[float, float, float, float]  # x, y, w, h — normalized 0-1 against image dims


@dataclass(frozen=True)
class EngineReading:
    engine: EngineName
    text: str
    duration_ms: int
    regions: tuple[TextRegion, ...] = ()
    #: Mean of `regions[].confidence` where region data exists; `None` for engines that
    #: return plain text with no confidence signal at all (Windows OCR, tier-0 text-layer).
    mean_confidence: float | None = None
    #: Which backend actually ran this reading — "cpu", "cuda", "openvino:npu", etc.
    device: str = "cpu"
    error: OcrError | None = None

    @classmethod
    def failure(cls, engine: EngineName, error: OcrError, duration_ms: int = 0) -> EngineReading:
        return cls(engine=engine, text="", duration_ms=duration_ms, error=error)


@dataclass(frozen=True)
class OcrRequest:
    run_id: str
    user_id: str
    image_ref: BlobRef
    engines: frozenset[EngineName]
    timeout_ms: int = 15_000


@dataclass(frozen=True)
class OcrResult:
    readings: tuple[EngineReading, ...]
    merged_text: str
    agreement: AgreementLevel
    confidence: float


class BlobStoreGateway(Protocol):
    """The whole surface every engine adapter and `service.py` need from Persistence —
    same shape as Preprocessing API's own `BlobStoreGateway` Protocol, defined separately
    here rather than shared, since a Protocol is a structural contract, not a value; two
    packages each naming the shape they need is the point of a Protocol seam
    (`docs/PRINCIPLES.md` §1.3), not duplication to collapse."""

    async def read_blob(self, ref: BlobRef) -> bytes: ...


@dataclass(frozen=True)
class OcrMetrics:
    reads_succeeded: int = 0
    reads_failed: int = 0
    engine_unavailable_count: int = 0
    engine_crashed_count: int = 0
    engine_timeout_count: int = 0
    cloud_calls_made: int = 0
    cloud_budget_exceeded_count: int = 0


__all__ = [
    "AgreementLevel",
    "BlobRef",
    "BlobStoreGateway",
    "EngineName",
    "EngineReading",
    "OcrError",
    "OcrErrorCode",
    "OcrMetrics",
    "OcrRequest",
    "OcrResult",
    "TextRegion",
]

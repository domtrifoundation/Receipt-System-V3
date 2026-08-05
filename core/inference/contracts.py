"""Inference API data contracts (`v3-deepdive-02-inference-api.md` §3).

This is the only module in this package other APIs import from. Same design choice as
OCR API: errors are data, not exceptions, at the API boundary (`GenerationResult.error`).

Every dict-typed field is a `FrozenDict` (`docs/PRINCIPLES.md` §2.1) — `ToolSpec.
parameters_schema`, `GenerationRequest.response_schema`, and `ToolCall.arguments` are all
JSON Schema/JSON-value shaped, genuinely mapping-typed, and cross a process boundary (a
`PresetWorker`'s own child process, `generation.py`), so a plain `dict` field would only be
shallowly immutable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from common.frozen_dict import FrozenDict


class ContentBlockType(str, Enum):
    TEXT = "text"
    IMAGE = "image"  # base64 or blob_ref, §7 — same shape family as OCR API's own image_ref


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(str, Enum):
    STOP = "stop"  # model naturally finished
    LENGTH = "length"  # hit max_tokens — see §5.2's truncation handling
    TOOL_CALL = "tool_call"
    ERROR = "error"


class InferenceErrorCode(str, Enum):
    """Wire-facing classification. Engine adapters/workers raise the matching internal
    exception from `errors.py`; the registry/generation layer catches it and produces this
    code — never a raw exception crossing this API's own boundary."""

    PRESET_NOT_CONFIGURED = "preset_not_configured"
    MODEL_LOAD_FAILED = "model_load_failed"
    GENERATION_TIMEOUT = "generation_timeout"
    GENERATION_CRASHED = "generation_crashed"
    WORKER_UNAVAILABLE = "worker_unavailable"
    SCHEMA_VIOLATION = "schema_violation"


@dataclass(frozen=True)
class InferenceError:
    code: InferenceErrorCode
    detail: str = ""


@dataclass(frozen=True)
class BlobRef:
    """Re-declared rather than imported from `core.persistence.contracts`, same reasoning
    as OCR API's own `contracts.BlobRef`: this package's `BlobStoreGateway` Protocol only
    ever needs `.logical_id`, so pinning Persistence's exact type would be an unneeded
    coupling."""

    logical_id: str


@dataclass(frozen=True)
class ContentBlock:
    type: ContentBlockType
    text: str | None = None
    image_ref: BlobRef | None = None


@dataclass(frozen=True)
class Message:
    role: MessageRole
    content: tuple[ContentBlock, ...]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    #: JSON Schema, shape owned by Tool Call API — Inference API only consumes it.
    parameters_schema: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class GenerationRequest:
    run_id: str
    user_id: str
    preset: str  # which configured model preset to use — caller's choice, not policy
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()  # empty = no tool-calling grammar built
    #: JSON Schema for constrained decoding — mutually exclusive with `tools` in practice.
    response_schema: FrozenDict | None = None
    max_tokens: int = 512
    temperature: float = 0.0
    timeout_ms: int = 30_000


@dataclass(frozen=True)
class GenerationResult:
    text: str  # empty when finish_reason == TOOL_CALL
    tool_call: ToolCall | None
    finish_reason: FinishReason
    schema_valid: bool  # did constrained output actually validate — see §5
    device: str  # "cpu", "cuda", "openvino:npu", etc. — same convention as OCR API
    duration_ms: int
    error: InferenceError | None = None

    @classmethod
    def failure(cls, error: InferenceError, duration_ms: int = 0, device: str = "cpu") -> GenerationResult:
        return cls(
            text="", tool_call=None, finish_reason=FinishReason.ERROR,
            schema_valid=False, device=device, duration_ms=duration_ms, error=error,
        )


class BlobStoreGateway(Protocol):
    """The whole surface `vision.py` needs from Persistence to resolve a `ContentBlock`'s
    `image_ref` into real bytes — same minimal shape as OCR API's and Preprocessing API's
    own `BlobStoreGateway` Protocols (`docs/PRINCIPLES.md` §1.3: a Protocol seam, not a
    shared type, since each package only needs to agree on the shape)."""

    async def read_blob(self, ref: BlobRef) -> bytes: ...


@dataclass(frozen=True)
class InferenceMetrics:
    generations_succeeded: int = 0
    generations_failed: int = 0
    generation_timeout_count: int = 0
    generation_crashed_count: int = 0
    model_load_failed_count: int = 0
    schema_violation_count: int = 0
    truncation_retry_count: int = 0


__all__ = [
    "BlobRef",
    "BlobStoreGateway",
    "ContentBlock",
    "ContentBlockType",
    "FinishReason",
    "GenerationRequest",
    "GenerationResult",
    "InferenceError",
    "InferenceErrorCode",
    "InferenceMetrics",
    "Message",
    "MessageRole",
    "ToolCall",
    "ToolSpec",
]

"""Preprocessing API's data contracts — types only, no logic (`docs/PRINCIPLES.md` §1.1).

This is the file every other API imports from (`v3-deepdive-03-preprocessing-api.md` §2).
`BlobRef` is imported directly from `core.persistence.contracts`, not redefined — a
`contracts.py`-to-`contracts.py` type import is the sanctioned exception to "never a direct
`core.x` import" (`docs/PRINCIPLES.md` §1.3's rule is about reaching another API's *logic*
through a concrete import; `core/account_guardian/contracts.py` already imports `BlobRef` this
same way).

Two decisions carry real weight here:

* **Errors are data** (§4.1, and this API's own §3): a `RasterResult`/`Variant` carries its own
  failure in an `error` field rather than raising. `VariantResult.variants` always contains one
  entry per requested kind, success or failure, never silently dropped — the same "OCR API
  never silently drops a requested engine" convention (`v3-deepdive-01-ocr-api.md` §3), applied
  here to variant kinds.
* **`kinds` is a `frozenset[VariantKind]`, caller's choice, never policy** — Preprocessing does
  not decide which variants a weak OCR reading needs (§1); it produces exactly what it is asked
  for and reports what happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from core.persistence.contracts import BlobRef

from .errors import PreprocessingError

__all__ = [
    "BlobStoreGateway",
    "PreprocessingMetrics",
    "RasterRequest",
    "RasterResult",
    "Variant",
    "VariantKind",
    "VariantRequest",
    "VariantResult",
]


@runtime_checkable
class BlobStoreGateway(Protocol):
    """Persistence's blob store, as seen from here — a `Protocol`, never a concrete
    `core.persistence` import (`docs/PRINCIPLES.md` §1.3), so this package stays importable and
    testable without Persistence installed. Narrow and purpose-specific: this API only ever
    needs to read a source file's bytes and write a new (rasterized/variant) image's bytes back,
    never anything about how or where Persistence actually stores them.
    """

    async def read_blob(self, ref: BlobRef) -> bytes: ...

    async def write_blob(self, data: bytes) -> BlobRef: ...


class VariantKind(str, Enum):
    """§3, §4 — the fixed, named variant set (§4.7's resolved fixed-vs-parametric decision).

    Order here has no significance of its own; `variant_registry.py`'s own registry is what
    maps each kind to its generator and default-enabled state.
    """

    STANDARD = "standard"
    BW_THRESHOLD = "bw_threshold"
    LOW_CONTRAST = "low_contrast"
    HIGH_CONTRAST = "high_contrast"
    CHANNEL_BOOST_RED = "channel_boost_red"
    CHANNEL_BOOST_GREEN = "channel_boost_green"
    CHANNEL_BOOST_BLUE = "channel_boost_blue"
    COLOR = "color"
    DESKEW = "deskew"
    DENOISE = "denoise"


@dataclass(frozen=True)
class RasterRequest:
    run_id: str
    user_id: str
    source_ref: BlobRef
    page_index: int = 0
    scale: float = 2.5


@dataclass(frozen=True)
class RasterResult:
    image_ref: BlobRef | None
    width: int
    height: int
    duration_ms: int
    device: str
    error: PreprocessingError | None = None
    """Populated, with `image_ref=None`, on failure — never raised across this API's own
    boundary (`docs/PRINCIPLES.md` §4.1)."""


@dataclass(frozen=True)
class VariantRequest:
    run_id: str
    user_id: str
    image_ref: BlobRef
    kinds: frozenset[VariantKind]
    device_preference: str = "auto"
    """`"auto" | "cpu" | "opencl"` — §6.1-6.2. A plain `str`, not an `Enum`: this is a
    three-way runtime hardware choice this API owns entirely, not a taxonomy Architect needs
    to know about."""


@dataclass(frozen=True)
class Variant:
    kind: VariantKind
    image_ref: BlobRef | None
    duration_ms: int
    device: str
    error: PreprocessingError | None = None
    """Populated, with `image_ref=None`, on failure — same non-raising convention as
    `RasterResult`."""


@dataclass(frozen=True)
class VariantResult:
    variants: tuple[Variant, ...]
    """One entry per requested kind, success or failure, always present — never silently
    dropped (§3's own stated convention, mirroring `v3-deepdive-01-ocr-api.md` §3's identical
    rule for `OcrResult.readings`)."""


@dataclass(frozen=True)
class PreprocessingMetrics:
    """This API's own counters, snapshotted (`metrics.py`). Field names are the counter
    names — `metrics.py` derives them from this contract so the two cannot drift apart, the
    same convention `core/health/metrics.py` established."""

    rasters_succeeded: int = 0
    rasters_failed: int = 0
    variants_succeeded: int = 0
    variants_failed: int = 0
    variants_run_on_opencl: int = 0
    variants_run_on_cpu: int = 0

"""Export Framework contracts (`v3-deepdive-31-export-framework.md` §2).

`ExportProvider` is a real `typing.Protocol` with a registry, never a per-format function
picked by an `if fmt == "xlsx"` branch. Each export type is one registered provider
consuming the same canonical data — that is the whole reason this framework exists rather
than a handful of one-off writers (`docs/PRINCIPLES.md` §1.2).

Exports are the one Provider Registry in this API where *simultaneous* execution is not the
point: a user asks for one export at a time. §1.2's own stated exception covers exactly
this — "swappable" here means "available in the registry, one selected when needed," because
running an SLSP and a QuickBooks export in parallel for one request produces no corroboration
value the way parallel OCR engines do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from common.frozen_dict import FrozenDict

from ..contracts import BlobRef


@dataclass(frozen=True)
class ExportResult:
    """One generated export. Errors are data (`docs/PRINCIPLES.md` §4.1)."""

    ok: bool
    export_blob_ref: BlobRef | None = None
    format: str = ""
    generated_at: datetime | None = None
    export_id: str = ""
    extra_artifacts: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class SlspResult:
    """SLSP produces two artifacts from one call, not two export types (§4.2).

    The `.xlsx` is a working/review copy; the `.dat` files are what BIR actually accepts.
    Either `.dat` is `None` when that quarter did not cross its own threshold — the sales
    list above ₱2,500,000 in quarterly sales, the purchases list above ₱1,000,000 net of VAT.
    """

    xlsx_review_copy: BlobRef
    sls_dat: BlobRef | None = None
    slp_dat: BlobRef | None = None


@runtime_checkable
class ExportProvider(Protocol):
    """One export format. Structural typing — providers do not inherit from this."""

    name: str
    format: str

    async def generate(self, user_id: str, params: FrozenDict) -> ExportResult:
        """Read canonical data, produce an artifact, return a reference to it.

        A provider never maintains its own copy or cache of business data, and never
        decides *when* it runs — a user action or Account Guardian's portability flow does.
        """
        ...


__all__ = ["ExportProvider", "ExportResult", "SlspResult"]

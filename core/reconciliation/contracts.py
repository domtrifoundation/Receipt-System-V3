"""Reconciliation data contracts (`v3-deepdive-17-reconciliation-api.md` §2, §3, §4, §6).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). It is the only file in this
package that anything outside `core/reconciliation/` imports from.

Four decisions here carry the weight:

* **Money is integer minor units (centavos), never a float.** §4.1's sketch is written with
  `float` subtotals and a `0.02` tolerance. A currency amount in binary floating point is a
  rounding bug waiting for a real invoice — `core/billing/` reached the same conclusion for the
  same reason, and a VAT-math *checker* that itself accumulates float error would flag correct
  receipts and pass incorrect ones. The tolerance is preserved exactly, expressed as 2 centavos.
* **`flag_type` is an unvalidated string behind a validator seam.** §1 is explicit that Architect
  owns the flag taxonomy and Reconciliation "produces flags of types Architect already
  registered, never inventing a new flag type inline" (`docs/PRINCIPLES.md` §3.4). The constants
  below are the names this package emits, not a taxonomy it defines.
* **Every check returns a `CheckResult` and nothing raises.** Errors are data (§4.1). A check
  that cannot run — a missing field, an unreachable provider — returns `INCONCLUSIVE`, which is
  deliberately not the same as `PASSED`. §4.12 makes that distinction explicitly for ATP: an
  illegible or missing field "is a genuinely different, softer case than a confirmed
  date-outside-window mismatch, and conflating the two would misrepresent the actual finding."
* **No check ever corrects anything.** §4.11: a discrepancy is "surfaced as a Review/Flagging
  flag rather than auto-corrected, consistent with every other check in this inventory that
  finds a discrepancy without unilaterally deciding which side is right"
  (`docs/PRINCIPLES.md` §4.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Protocol, runtime_checkable

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Aware rather than naive because §4.3 does date arithmetic against an upload timestamp, and
    naive-versus-aware subtraction raises in the middle of a check rather than at its edge.
    """
    return datetime.now(timezone.utc)


class Severity(str, Enum):
    """How loudly a hit should be surfaced. §4.1 names `medium` for VAT math directly.

    A presentation-ordering vocabulary internal to this API, not a taxonomy — Review/Flagging
    decides what a severity *does*, and Architect owns what flag types exist.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CheckOutcome(str, Enum):
    """The three genuinely distinct things a check can conclude.

    `INCONCLUSIVE` is not a failure and not a pass. §4.12's ATP reasoning generalises to the
    whole inventory: "an ATP field OCR failed to capture at all is a genuinely different, softer
    case than a confirmed date-outside-window mismatch". A two-state result forces one into the
    other and both directions are wrong — treating missing data as a hit floods the review queue,
    treating it as a pass silently certifies unchecked receipts as clean.
    """

    PASSED = "passed"
    FLAGGED = "flagged"
    INCONCLUSIVE = "inconclusive"


#: The flag type names this package emits. **Architect owns the taxonomy** (§1); these are the
#: strings this API produces, and a name here Architect has not registered is a wiring bug to
#: catch at the validator seam, not a type this package has thereby defined
#: (`docs/PRINCIPLES.md` §3.4). A `FrozenDict` per §2.1.1 — a lookup table one caller can edit
#: is a lookup table every caller shares the edit of.
FLAG_TYPES: FrozenDict = FrozenDict(
    {
        "vat_math": "vat_math_mismatch",
        "tin_format": "tin_format_invalid",
        "date_plausibility": "date_implausible",
        "account_outlier": "amount_outlier",
        "semantic_duplicate": "semantic_duplicate",
        "vendor_group_mismatch": "vendor_group_mismatch",
        "items_vendor_mismatch": "items_vendor_mismatch",
        "bir_completeness": "bir_fields_incomplete",
        "orphaned_archive_reference": "orphaned_archive_reference",
        "geo_vendor_cross_reference": "geo_vendor_discrepancy",
        "atp_validity": "atp_expired",
        "reimport_conflict": "reimport_conflict",
        "content_confirmed_malicious": "content_confirmed_malicious",
    }
)

#: Philippine standard VAT, as an integer percentage (§4.1). Integer rather than `0.12` so the
#: arithmetic in `vat_math.py` never leaves exact integer space.
VAT_RATE_PERCENT: int = 12

#: §4.1's rounding tolerance, in centavos. Two centavos — the same 0.02 pesos that sketch names,
#: expressed in the unit the arithmetic actually uses.
VAT_TOLERANCE_CENTAVOS: int = 2

#: §4.1 computes VAT against a vatable base. A receipt that is zero-rated or VAT-exempt has a
#: legitimately zero VAT amount, and checking 12% against it would flag every export sale and
#: every senior-citizen or PWD discounted purchase in the country. These are the treatments this
#: package knows how to reason about; anything else is `INCONCLUSIVE` rather than guessed at.
VATABLE = "vatable"
ZERO_RATED = "zero_rated"
VAT_EXEMPT = "vat_exempt"
KNOWN_VAT_TREATMENTS: frozenset[str] = frozenset({VATABLE, ZERO_RATED, VAT_EXEMPT})


@dataclass(frozen=True)
class CheckResult:
    """One check's conclusion about one receipt — errors as data (§4.1).

    `flag_type` is empty unless `outcome` is `FLAGGED`. §6's own wire comment says "empty
    flag_type = passed", and that shape is preserved; `outcome` is what makes the third state
    expressible alongside it rather than instead of it.
    """

    check_name: str
    outcome: CheckOutcome = CheckOutcome.PASSED
    flag_type: str = ""
    severity: Severity = Severity.MEDIUM
    detail: str = ""
    evidence: FrozenDict = field(default_factory=lambda: FrozenDict({}))

    @property
    def flagged(self) -> bool:
        return self.outcome is CheckOutcome.FLAGGED


@dataclass(frozen=True)
class ReceiptSnapshot:
    """Everything the check inventory reads about one receipt.

    A single frozen snapshot rather than each check fetching its own fields: §5 says the checks
    are "mostly fast, pure-Python logic over already-fetched data", and eleven checks each
    issuing their own read would make a retroactive sweep N times more expensive than the live
    path — the exact divergence `docs/PRINCIPLES.md` §1.9 exists to prevent.

    Amounts are integer centavos throughout. See this module's docstring.
    """

    receipt_id: str
    vendor_name: str = ""
    vendor_tin: str = ""
    transaction_date: date | None = None
    uploaded_at: datetime | None = None
    subtotal_centavos: int | None = None
    vat_centavos: int | None = None
    total_centavos: int | None = None
    vat_treatment: str = VATABLE
    receipt_number: str = ""
    atp_number: str = ""
    atp_valid_from: date | None = None
    atp_valid_until: date | None = None
    address: str = ""
    logical_id: str = ""
    item_categories: tuple[str, ...] = ()
    vendor_category: str = ""
    vendor_group: str = ""


@dataclass(frozen=True)
class PropagationJob:
    """§3's correction-propagation job.

    `receipts_resumed` is not decoration: §8 resolves propagation atomicity by reusing Execution
    Core's own checkpoint mechanism, and the observable that proves an interrupted batch resumed
    rather than restarted is the count of receipts it skipped because they were already done.
    """

    job_id: str
    entity_type: str
    entity_id: str
    change: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    receipts_total: int = 0
    receipts_propagated: int = 0
    receipts_resumed: int = 0
    conflicts: tuple[str, ...] = ()
    error: str = ""

    @property
    def complete(self) -> bool:
        return not self.error and self.receipts_propagated == self.receipts_total


@runtime_checkable
class FlagTypeValidator(Protocol):
    """The seam onto Architect's flag taxonomy (§1, `docs/PRINCIPLES.md` §3.4).

    Deliberately shaped so an unrecognised type is *reported*, not rejected — the same choice
    `core/review_flagging/` made and for the same reason: rejecting an unknown type would make a
    newly-added check's findings vanish until someone remembered to register it, which is a
    silent failure where a surfaced one was available.
    """

    def is_registered(self, flag_type: str) -> bool: ...


@runtime_checkable
class FlagEmitter(Protocol):
    """Review/Flagging's flag-creation surface. Reconciliation produces flags; it never decides
    what one means, who sees it, or when it resolves."""

    async def create_flag(
        self, receipt_id: str, flag_type: str, details: FrozenDict | None = None
    ) -> None: ...


@runtime_checkable
class VendorHistoryProvider(Protocol):
    """§4.4's input: Architect's own learned vendor/category history.

    A `Protocol` because §4.4 makes this check "a genuine consumer of Architect's registry
    rather than self-contained logic" — and because a direct import of `core.architect` would
    make this package unimportable wherever Architect is not installed
    (`docs/PRINCIPLES.md` §1.3).
    """

    async def historical_amounts(self, vendor_name: str, category: str) -> tuple[int, ...]: ...


@runtime_checkable
class BlobLocationChecker(Protocol):
    """§4.10's seam onto Disaster Recovery's own `BlobLocation`-existence check.

    §4.10 is emphatic that this check "reuses Disaster Recovery's own verification logic
    directly (same check, different trigger and scope)" rather than reimplementing it. This
    Protocol is that seam; the identity of the function behind it is what a
    `docs/PRINCIPLES.md` §1.9 test pins.
    """

    async def blob_exists(self, logical_id: str) -> bool: ...


@runtime_checkable
class DuplicateCandidateSource(Protocol):
    """§4.5's candidate lookup — receipts sharing this one's vendor and transaction date."""

    async def candidates_for(self, snapshot: ReceiptSnapshot) -> tuple[ReceiptSnapshot, ...]: ...


@runtime_checkable
class ReceiptWriter(Protocol):
    """§3's write path, returning `(applied, conflict_detail)` — errors as data (§4.1).

    Corrections go through Persistence's *normal* write path so every propagated correction is
    automatically Historian-logged with `actor: "worker"`, distinguishable from a human's direct
    edit. A bulk-update shortcut around it would make propagated corrections indistinguishable
    from someone having typed them.
    """

    async def apply_correction(self, receipt_id: str, change: FrozenDict) -> tuple[bool, str]: ...


__all__ = [
    "BlobLocationChecker",
    "CheckOutcome",
    "CheckResult",
    "DuplicateCandidateSource",
    "FLAG_TYPES",
    "FlagEmitter",
    "FlagTypeValidator",
    "KNOWN_VAT_TREATMENTS",
    "PropagationJob",
    "ReceiptSnapshot",
    "ReceiptWriter",
    "Severity",
    "VAT_EXEMPT",
    "VAT_RATE_PERCENT",
    "VAT_TOLERANCE_CENTAVOS",
    "VATABLE",
    "VendorHistoryProvider",
    "ZERO_RATED",
    "utcnow",
]

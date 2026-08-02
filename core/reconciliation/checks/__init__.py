"""§4's check inventory, and the one place it is assembled.

`default_registry()` is the whole inventory §4 specifies. It is a function rather than a
module-level instance because `CheckRegistry` is mutable — a shared singleton would let one
caller's registration change what every other caller's sweep runs, and a self-hosted install
that registered an extra check would silently alter the hosted service's behaviour in the same
process.

**Nine of §4's twelve numbered items are checks in this package; three are not, deliberately.**
§4.8 (reimport conflict) and §4.9 (confirmed-malicious content) are explicitly "surfaced, not
owned, here" — Persistence's Reimport sub-API and Content Security respectively already reached
those verdicts, and this API is purely the routing step that turns one into a flag. They live in
`surfacing.py` rather than as checks, because a "check" that re-derives a conclusion another API
already owns is the second implementation `docs/PRINCIPLES.md` §1.9 exists to prevent. §4.6 is
one numbered item covering two genuinely distinct checks, which is why the count comes out at
eleven check modules against twelve numbered subsections.
"""

from __future__ import annotations

from .account_outlier import AccountOutlierCheck
from .atp_validity import AtpValidityCheck
from .base import CheckRegistry, ReconciliationCheck
from .bir_completeness import BirCompletenessCheck
from .date_plausibility import DatePlausibilityCheck
from .geo_vendor_cross_reference import GeoVendorCrossReferenceCheck
from .items_vendor_mismatch import ItemsVendorMismatchCheck
from .orphaned_archive_reference import OrphanedArchiveReferenceCheck
from .semantic_duplicate import SemanticDuplicateCheck
from .tin_format import TinFormatCheck
from .vat_math import VatMathCheck
from .vendor_group_mismatch import VendorGroupMismatchCheck

#: Every check §4 specifies, in the order §4 introduces them. A tuple of classes rather than of
#: instances so `default_registry()` builds fresh ones each time — see this module's docstring.
INVENTORY: tuple[type, ...] = (
    VatMathCheck,
    TinFormatCheck,
    DatePlausibilityCheck,
    AccountOutlierCheck,
    SemanticDuplicateCheck,
    VendorGroupMismatchCheck,
    ItemsVendorMismatchCheck,
    BirCompletenessCheck,
    OrphanedArchiveReferenceCheck,
    GeoVendorCrossReferenceCheck,
    AtpValidityCheck,
)


def default_registry() -> CheckRegistry:
    """A registry holding one instance of every check in §4's inventory."""
    registry = CheckRegistry()
    for check_class in INVENTORY:
        registry.register(check_class())
    return registry


__all__ = [
    "AccountOutlierCheck",
    "AtpValidityCheck",
    "BirCompletenessCheck",
    "CheckRegistry",
    "DatePlausibilityCheck",
    "GeoVendorCrossReferenceCheck",
    "INVENTORY",
    "ItemsVendorMismatchCheck",
    "OrphanedArchiveReferenceCheck",
    "ReconciliationCheck",
    "SemanticDuplicateCheck",
    "TinFormatCheck",
    "VatMathCheck",
    "VendorGroupMismatchCheck",
    "default_registry",
]

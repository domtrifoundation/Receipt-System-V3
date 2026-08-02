"""§4.2 — the TIN format check.

BIR TINs follow a known structure: 9 base digits, optionally a 3-digit branch/RDO suffix,
conventionally dash-grouped as `NNN-NNN-NNN` or `NNN-NNN-NNN-NNN`.

**§4.2 is explicit about what this check is not**: it is "a regex-level structural check, not a
validity check against BIR's own records (that would need an actual BIR lookup service this
project doesn't have access to; this check catches OCR misreads and malformed entries, not
fraudulent-but-well-formatted TINs)." That boundary is the difference between a check that is
honest about its own power and one that implies an authority it does not have — a passing result
here means "this looks like a TIN", never "this TIN is real".

The historical 5-digit branch code exists on older receipts and is accepted; rejecting it would
flag every pre-2010 receipt in an archive as malformed, which is exactly the false-positive class
a retroactive sweep must not produce.
"""

from __future__ import annotations

import re

from common.frozen_dict import FrozenDict

from ..contracts import FLAG_TYPES, ReceiptSnapshot, Severity
from .base import flagged, inconclusive, passed

CHECK_NAME = "tin_format"

#: Nine base digits, optionally a branch/RDO suffix of 3 or 5 digits. Dashes and spaces are
#: stripped before matching rather than being made part of the pattern: OCR reads a dash as a
#: hyphen, an en-dash, or nothing at all depending on the scan, and a receipt is not malformed
#: because its separator rendered oddly. What this check is actually about is the digits.
TIN_PATTERN = re.compile(r"^\d{9}(\d{3}|\d{5})?$")

#: Separators seen on real receipts and in real data entry. Stripped before matching.
_SEPARATORS = re.compile(r"[\s\-‐-―./]")


def normalize_tin(raw: str) -> str:
    """Strip separators, leaving only what the structural check is about."""
    return _SEPARATORS.sub("", raw.strip())


def is_structurally_valid(raw: str) -> bool:
    """Whether `raw` has the shape of a BIR TIN. Says nothing about whether it exists."""
    return bool(TIN_PATTERN.match(normalize_tin(raw)))


class TinFormatCheck:
    """§4.2, as a registry entry."""

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        raw = snapshot.vendor_tin.strip()
        if not raw:
            return inconclusive(
                CHECK_NAME,
                "no TIN on this receipt — absence is BIR completeness's finding, not a "
                "malformed-TIN finding",
            )

        normalized = normalize_tin(raw)
        if is_structurally_valid(raw):
            return passed(CHECK_NAME, "TIN is structurally well-formed (existence not checked)")

        return flagged(
            CHECK_NAME,
            FLAG_TYPES["tin_format"],
            Severity.MEDIUM,
            (
                f"{raw!r} is not a structurally valid BIR TIN "
                f"({len(normalized)} digits after stripping separators; expected 9, 12 or 14)"
            ),
            FrozenDict({"raw": raw, "normalized": normalized, "digits": len(normalized)}),
        )


__all__ = [
    "CHECK_NAME",
    "TIN_PATTERN",
    "TinFormatCheck",
    "is_structurally_valid",
    "normalize_tin",
]

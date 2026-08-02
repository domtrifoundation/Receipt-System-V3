"""§4.10 — orphaned/missing archive-reference detection.

§4.10 records this as "a real, previously-missed check... a clean miss, not a rename or a
fold-in": it was in Background Workers' own job-inventory discussion (§6.3 there) and never made
it into this inventory until a correction pass caught it.

**This check reuses Disaster Recovery's own verification logic rather than reimplementing it**,
which is `docs/PRINCIPLES.md` §1.9 in its most literal form — §4.10's own words are "same check,
different trigger and scope — one receipt or a small batch here, not a full-instance walk". The
`BlobLocationChecker` Protocol is that seam. A second implementation of "does this blob exist"
would drift from Disaster Recovery's within one release, and the failure would be silent in the
worst possible direction: a routine sweep reporting archives intact that a real recovery would
find missing.

**It finds the problem and does not repair it**, and §4.10 says why in the sketch it ships with:
"a missing blob for a receipt that's supposedly already processed is exactly the kind of thing a
human should look at before deciding what to do." An automatic repair would have to guess whether
the row or the blob is the wrong one, and both guesses destroy evidence.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import BlobLocationChecker, FLAG_TYPES, ReceiptSnapshot, Severity
from .base import flagged, inconclusive, passed

CHECK_NAME = "orphaned_archive_reference"


class OrphanedArchiveReferenceCheck:
    """§4.10, as a registry entry. Reads `blob_locations` from the run context."""

    @property
    def name(self) -> str:
        return CHECK_NAME

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict):
        if not snapshot.logical_id:
            return inconclusive(
                CHECK_NAME, "this receipt references no logical_id — nothing to verify"
            )

        checker = context.get("blob_locations")
        if not isinstance(checker, BlobLocationChecker):
            return inconclusive(
                CHECK_NAME,
                "no blob-location checker supplied; §4.10 reuses Disaster Recovery's own "
                "verification rather than reimplementing it",
            )

        try:
            exists = await checker.blob_exists(snapshot.logical_id)
        except Exception as exc:  # noqa: BLE001 - errors are data (§4.1)
            return inconclusive(
                CHECK_NAME,
                f"blob-location lookup failed ({type(exc).__name__}: {exc}); an unreachable "
                "archive is not evidence a blob is missing",
            )

        if not exists:
            return flagged(
                CHECK_NAME,
                FLAG_TYPES["orphaned_archive_reference"],
                Severity.HIGH,
                (
                    f"receipt references logical_id {snapshot.logical_id!r} with no "
                    "corresponding BlobLocation — found, not repaired"
                ),
                FrozenDict({"logical_id": snapshot.logical_id}),
            )

        return passed(CHECK_NAME, "archive reference resolves to a real blob location")


__all__ = ["CHECK_NAME", "OrphanedArchiveReferenceCheck"]

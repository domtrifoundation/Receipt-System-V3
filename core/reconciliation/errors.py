"""Reconciliation's error taxonomy.

**These types are for in-process control flow, never for crossing a boundary**
(`docs/PRINCIPLES.md` §4.1). Everything a caller reaches over gRPC comes back as a result object
with an `.error` field or an `INCONCLUSIVE` outcome — `CheckResult`, `PropagationJob`. There is
no raise-loudly carve-out here; nothing in this package is a security decision, and a check that
raised across the boundary would take down a sweep over ten thousand receipts because one row
was malformed.
"""

from __future__ import annotations


class ReconciliationError(Exception):
    """Base for everything this package raises internally."""


class DuplicateCheckName(ReconciliationError):
    """Two checks registered under one name (`checks/base.py`).

    Raised rather than resolved because the alternative is silent: one of the two checks stops
    running and nothing anywhere reports that it did.
    """


class PropagationConflict(ReconciliationError):
    """A correction disagrees with a receipt's current value.

    Defined for callers that would rather handle a conflict as an exception in their own
    in-process code. `propagate_correction` itself never raises it — a bulk sweep records
    conflicts in `PropagationJob.conflicts` and keeps going, because one contested receipt is not
    a reason to abandon the other nine thousand (`docs/PRINCIPLES.md` §4.3 asks for the conflict
    to be surfaced, not for the batch to stop).
    """


__all__ = ["DuplicateCheckName", "PropagationConflict", "ReconciliationError"]

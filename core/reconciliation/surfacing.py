"""§4.8 and §4.9 — the two findings this API surfaces without owning.

Both are deliberately *not* checks, and §2's package layout does not list this file, so it is
recorded here and in `CLAUDE.md` as an addition with a reason.

**§4.8, reimport conflict**: Persistence's Reimport sub-API "already owns diff/conflict detection
for a reimported file against current canonical state — Reconciliation doesn't reimplement that
logic, it's simply the API that turns a detected conflict into a Review/Flagging flag of the
already-registered `reimport_conflict` type."

**§4.9, confirmed-malicious content**: Content Security's own staff-confirmed verdict flows into
a flag "the same way — Reconciliation never re-runs a security scan itself, it's purely a
routing/surfacing step for a verdict another API already reached."

Putting these in `checks/` would have made them look like checks, and a "check" that re-derives a
conclusion another API already owns is precisely the second implementation
`docs/PRINCIPLES.md` §1.9 exists to prevent. Worse for §4.9 specifically: a security verdict
re-derived here would be a second, weaker scanner whose disagreement with Content Security's own
would have no defined resolution, against a §4.2 rule that says security failures are closed, not
negotiated.

So these functions take a verdict another API reached and produce a flag. They do not inspect a
receipt, they do not decide, and neither of them can conclude "actually, this is fine."
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from .contracts import CheckOutcome, CheckResult, FLAG_TYPES, Severity

REIMPORT_CHECK_NAME = "reimport_conflict"
CONTENT_CHECK_NAME = "content_confirmed_malicious"


def surface_reimport_conflict(
    receipt_id: str, conflicting_fields: tuple[str, ...], detail: str = ""
) -> CheckResult:
    """§4.8: turn Persistence's already-detected reimport conflict into a flag.

    An empty `conflicting_fields` produces no flag — not because this function re-checked and
    found nothing, but because there was no conflict reported to surface. Fabricating a flag
    from an empty conflict set would put a finding in a human's queue that no API ever made.
    """
    if not conflicting_fields:
        return CheckResult(
            check_name=REIMPORT_CHECK_NAME,
            outcome=CheckOutcome.PASSED,
            detail="no reimport conflict was reported for this receipt",
        )
    return CheckResult(
        check_name=REIMPORT_CHECK_NAME,
        outcome=CheckOutcome.FLAGGED,
        flag_type=FLAG_TYPES["reimport_conflict"],
        severity=Severity.HIGH,
        detail=detail or f"reimport disagrees with canonical state on: {', '.join(conflicting_fields)}",
        evidence=FrozenDict({"receipt_id": receipt_id, "fields": conflicting_fields}),
    )


def surface_confirmed_malicious(
    receipt_id: str, confirmed: bool, verdict_detail: str = ""
) -> CheckResult:
    """§4.9: turn Content Security's staff-confirmed verdict into a flag.

    `confirmed` comes from Content Security; this function has no opinion about it and no way to
    reach one. Severity is always `HIGH` — a confirmed-malicious verdict is not a matter of
    degree, and `docs/PRINCIPLES.md` §4.2's fail-closed posture means the one thing this routing
    step must never do is soften a verdict on its way to a human.
    """
    if not confirmed:
        return CheckResult(
            check_name=CONTENT_CHECK_NAME,
            outcome=CheckOutcome.PASSED,
            detail="no confirmed-malicious verdict was reported for this receipt",
        )
    return CheckResult(
        check_name=CONTENT_CHECK_NAME,
        outcome=CheckOutcome.FLAGGED,
        flag_type=FLAG_TYPES["content_confirmed_malicious"],
        severity=Severity.HIGH,
        detail=verdict_detail or "Content Security staff confirmed this content malicious",
        evidence=FrozenDict({"receipt_id": receipt_id}),
    )


__all__ = [
    "CONTENT_CHECK_NAME",
    "REIMPORT_CHECK_NAME",
    "surface_confirmed_malicious",
    "surface_reimport_conflict",
]

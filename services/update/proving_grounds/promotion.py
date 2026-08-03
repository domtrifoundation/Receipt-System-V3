"""`gate_promotion()` — §4's own signature: "a candidate only promotes to a channel if
its test result passes the same health-check discipline a code release's own rollout
cutover already uses — not a separate, looser bar just because it's a dependency bump
rather than a code change."

**The gate itself is deliberately simple and total: `result.ok and result.passed`.**
There is no looser path — a `TestResult` whose test could not even run (`ok=False`, a
download failure or an unavailable dispatcher) never promotes, and neither does one that
ran and genuinely failed (`passed=False`). §7's own "promotion-gate bypass test" hook
exists to prove there is no other code path into a channel that skips this function
entirely — every promotion decision must go through here.
"""

from __future__ import annotations

from .contracts import TestCandidate, TestResult

__all__ = ["gate_promotion"]


async def gate_promotion(channel: str, candidate: TestCandidate, result: TestResult) -> bool:
    """Whether `candidate` may be promoted to `channel`, given `result`.

    `channel`/`candidate` are accepted for the audit trail a real caller builds around
    this decision (which channel, what was being promoted) — the gate logic itself reads
    only `result`, since the same health-check discipline applies identically regardless
    of what is being promoted or where.
    """
    return result.ok and result.passed

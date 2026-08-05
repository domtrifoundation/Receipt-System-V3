"""One file per migration step, never a monolith (§2, §3).

§3 states the constraint and the reason: each step is "small and independently testable (one
file per version bump) rather than one large function handling every possible version
transition — a real, deliberate constraint given how much easier a small, focused diff is to
review and reason about correctness for than a sprawling multi-version conditional."

`register_all` is the one place a new step becomes live. Adding `v2_to_v3.py` means adding one
import and one call here, which is also what makes the chain-integrity check (§8) meaningful:
a step file that exists but was never registered is a gap, and the check finds it.

**There are no real steps yet, and that is correct rather than incomplete.** Every structure
kind is at version 1 (`contracts.CURRENT_VERSIONS`), so there is no bump to write a step for —
the first one arrives with the first release that changes a persisted shape. `v1_to_v2.py`
exists as the worked example §2's layout names, registered only in tests, so the shape a real
step takes is written down before anyone needs to write one under time pressure.
"""

from __future__ import annotations

from ..registry import MigrationRegistry


def register_all(registry: MigrationRegistry) -> None:
    """Register every shipped migration step into `registry`.

    Empty today. When the first real bump lands, it registers here — and the chain-integrity
    check in `tests/unit/core/migration/` will require it, because `CURRENT_VERSIONS` moving
    to 2 without a 1->2 step is exactly the gap that check exists to catch.
    """
    return None


__all__ = ["register_all"]

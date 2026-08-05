"""Execution Core's error taxonomy (`v3-deepdive-10-execution-core-api.md`).

**These types are for in-process control flow, never for crossing a boundary**
(`docs/PRINCIPLES.md` §4.1). Everything a caller reaches over gRPC comes back as a result
object with an `.error` field — `StageAttempt`, `ReceiptOutcome`, `RunOutcome`,
`TransitionResult`. Execution Core has no equivalent of Auth's deliberate raise-loudly carve-out;
nothing in this package is a security decision.

`CheckpointWriteFailed` is the one that matters. A stage whose work succeeded but whose
checkpoint could not be written must fail loudly *inside* the retry machinery, because the
alternative is silently redoing that stage's work on every subsequent attempt — and the
expensive stages this design exists to protect (OCR corroboration, Inference generation) are
exactly the ones that would be redone. §6's entire value proposition is that they are not.
"""

from __future__ import annotations


class ExecutionCoreError(Exception):
    """Base for everything this package raises internally."""


class CheckpointWriteFailed(ExecutionCoreError):
    """A stage completed but its checkpoint could not be recorded (§6).

    Deliberately fatal to the attempt rather than swallowed: an uncheckpointed success is
    indistinguishable from a failure on the next pass, so treating it as success would let the
    run believe expensive work was durable when it was not.
    """


class StageFailed(ExecutionCoreError):
    """The stage's own callable raised. Counted by `retry_policy.attempt_stage` (§7)."""


class RunNotFound(ExecutionCoreError):
    """A run id with no run behind it — a caller-side mistake, surfaced as data at the edge."""


class NoCapacity(ExecutionCoreError):
    """Neither concurrency axis had room (§5.1). Raised only by the non-blocking acquire path."""


__all__ = [
    "CheckpointWriteFailed",
    "ExecutionCoreError",
    "NoCapacity",
    "RunNotFound",
    "StageFailed",
]

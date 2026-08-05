"""Execution Core data contracts (`v3-deepdive-10-execution-core-api.md` §3, §5, §7, §11, §12).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). It is the only file in this
package that anything outside `services/execution_core/` imports from.

Four decisions here carry the weight:

* **`RunState.RUNNING` exists and is deliberately unreachable.** §3's own sketch lists it, and
  §3's prose immediately explains why it is not a fifth state: a run that is actually
  processing is always more precisely `OPEN` or `CLOSING`. Deleting the member would break a
  caller that still sends the string; leaving it assignable would reintroduce exactly the
  ambiguous state §3 says to avoid. So it stays in the enum, `ASSIGNABLE_STATES` excludes it,
  and `state_machine.py`'s transition table gives nothing a path into it.
* **Run-level idempotency is keyed on content hash, never on mtime** (§4). V2's own
  `_file_fingerprint()` validated this the hard way: cloud sync (Drive/OneDrive/Dropbox)
  touches mtime on bytes that did not change, so an mtime-keyed check reprocesses receipts
  that are already fully written.
* **Every collaborator is a `Protocol`, never a concrete import** (`docs/PRINCIPLES.md` §1.3).
  Execution Core calls seven other APIs; importing any of their packages directly would make
  this one un-runnable — and un-testable — unless all seven were installed and reachable.
* **Errors are data** (§4.1). `StageAttempt` and `RunOutcome` carry their failure in a field.
  Nothing in this package raises across a boundary a gRPC call would cross.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Aware rather than naive because a run's debounce ceiling is arithmetic on timestamps, and
    naive-versus-aware subtraction raises at exactly the moment a run is trying to close.
    """
    return datetime.now(timezone.utc)


class RunState(str, Enum):
    """A run's lifecycle state (§3).

    `RUNNING` is a legacy-compatibility alias and is never a run's actual state — see this
    module's docstring and `state_machine.ASSIGNABLE_STATES`.
    """

    WAITING_FOR_TRIGGER = "waiting_for_trigger"
    OPEN = "open"
    CLOSING = "closing"
    RUNNING = "running"
    PAUSED = "paused"
    SHUTTING_DOWN = "shutting_down"


class ReceiptStage(str, Enum):
    """One receipt's position in the pipeline (§3).

    Ordered exactly as §1's sequence runs: Ingestion → Preprocessing → OCR → Matching → Geo →
    Inference → Persistence write. `STAGE_SEQUENCE` below is the one place that ordering is
    written down; nothing else in this package hardcodes it.
    """

    INGESTED = "ingested"
    PREPROCESSED = "preprocessed"
    OCRD = "ocrd"
    MATCHED = "matched"
    GEOD = "geod"
    INFERRED = "inferred"
    WRITTEN = "written"


#: §1's pipeline sequence, as data. A tuple rather than a list because the order is the
#: contract — an accidental `.append` or `.sort` on a shared module-level list would reorder
#: the pipeline for every run in the process (`docs/PRINCIPLES.md` §2.1.1's reasoning applied
#: to a sequence rather than a mapping).
STAGE_SEQUENCE: tuple[ReceiptStage, ...] = (
    ReceiptStage.INGESTED,
    ReceiptStage.PREPROCESSED,
    ReceiptStage.OCRD,
    ReceiptStage.MATCHED,
    ReceiptStage.GEOD,
    ReceiptStage.INFERRED,
    ReceiptStage.WRITTEN,
)

#: The terminal stage. A receipt that reaches it is fully in the system, which is what §4's
#: run-level idempotency check looks for.
TERMINAL_STAGE: ReceiptStage = ReceiptStage.WRITTEN

#: The states a run can actually be in while it is processing (§3). "Running" is what these two
#: collectively mean, which is precisely why it is not a third member here.
ACTIVE_STATES: frozenset[RunState] = frozenset({RunState.OPEN, RunState.CLOSING})


class VendorCorroborationPolicy(str, Enum):
    """§12's `vendor_match.corroboration_policy`, passed through to Matching's own §5.2 gate.

    Execution Core carries this value and applies nothing itself — Matching owns what
    corroboration means. Duplicating the decision here would be the second implementation
    `docs/PRINCIPLES.md` §1.9 exists to prevent.
    """

    ALWAYS = "always"
    BELOW_THRESHOLD = "below_threshold"
    NEVER = "never"


class StageOutcome(str, Enum):
    """How one attempt at one stage ended (§7).

    `ESCALATED` is distinct from `FAILED` on purpose: a failed attempt will be retried, an
    escalated one never will be. Collapsing them into a single falsy return is what makes a
    caller unable to tell "this stage produced nothing" from "this receipt has given up".
    """

    COMPLETED = "completed"
    RESUMED = "resumed"
    FAILED = "failed"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class StageCheckpoint:
    """One stage's completion record (§6).

    `stage_output_ref` is whatever that stage produced — a blob reference for OCR, a structured
    result for Inference. Dict-shaped outputs are `FrozenDict` per the project-wide policy
    (`docs/PRINCIPLES.md` §2.1, and Tool Call's deep-dive §6), so a resumed stage cannot have
    its recorded output mutated by whichever caller happens to read it next.

    `content_hash` is on the checkpoint rather than looked up elsewhere because §4's run-level
    idempotency check asks a question about content, not about a receipt id: the same bytes
    arriving under a new id must still be recognised as already written.
    """

    receipt_id: str
    run_id: str
    stage: ReceiptStage
    completed_at: datetime
    stage_output_ref: Any = None
    content_hash: str = ""


@dataclass(frozen=True)
class Run:
    """One batch of receipts moving through the pipeline together (§3, §5.2)."""

    run_id: str
    user_id: str
    state: RunState
    opened_at: datetime
    closing_started_at: datetime | None = None
    receipt_count: int = 0
    #: §5.2's debounce window expiry, recomputed on each trigger. Never later than
    #: `opened_at + max_wait`; the ceiling wins.
    window_expires_at: datetime | None = None
    #: §5.2's hard ceiling, measured from `opened_at` and never from the most recent trigger.
    ceiling_at: datetime | None = None


@dataclass(frozen=True)
class RunProgress:
    """§11's streamed progress payload.

    Server-streamed rather than returned once at the end, which is the direct fix for V2's
    "results only show at end of run".
    """

    run_id: str
    state: RunState
    receipts_total: int = 0
    receipts_completed: int = 0
    current_stage_summary: str = ""


@dataclass(frozen=True)
class StageAttempt:
    """The result of one `attempt_stage` call (§7) — errors as data (§4.1).

    §7's own sketch returns `None` on escalation, which cannot be told apart from a stage whose
    genuine output is `None`. A caller that mistakes one for the other either retries a receipt
    that has already given up or abandons one that merely produced nothing.
    """

    stage: ReceiptStage
    outcome: StageOutcome
    value: Any = None
    attempts: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome in (StageOutcome.COMPLETED, StageOutcome.RESUMED)


@dataclass(frozen=True)
class ReceiptOutcome:
    """How one receipt's whole pass through the pipeline ended."""

    receipt_id: str
    run_id: str
    reached_stage: ReceiptStage | None = None
    outcome: StageOutcome = StageOutcome.COMPLETED
    skipped_as_duplicate: bool = False
    error: str = ""

    @property
    def written(self) -> bool:
        return self.reached_stage is TERMINAL_STAGE


@dataclass(frozen=True)
class RunOutcome:
    """How a whole run ended — errors as data, never an exception across the boundary (§4.1)."""

    run_id: str
    state: RunState
    receipts: tuple[ReceiptOutcome, ...] = ()
    cancelled_after: int = 0
    error: str = ""


@dataclass(frozen=True)
class ConcurrencyConfig:
    """§12's two independent knobs (§5.1).

    `per_user_limit` defaults to 1 and doubles as rate limiting; `global_limit` protects shared
    OCR/Inference hardware regardless of how many distinct users are asking at once.
    """

    per_user_limit: int = 1
    global_limit: int = 8


@dataclass(frozen=True)
class DebounceConfig:
    """§12's debounce values — §14 locks these in as the shipping defaults, not placeholders."""

    window_seconds: float = 10.0
    max_wait_seconds: float = 120.0


@dataclass(frozen=True)
class RetryConfig:
    """§12's retry knob. §7's escalation happens at the cap, not an unbounded loop."""

    max_attempts_per_stage: int = 3


@dataclass(frozen=True)
class VendorMatchConfig:
    """§12's Matching pass-through. `below_threshold_bar` is only meaningful for one policy."""

    corroboration_policy: VendorCorroborationPolicy = VendorCorroborationPolicy.ALWAYS
    below_threshold_bar: float = 0.75


@dataclass(frozen=True)
class ExecutionConfig:
    """§12's whole config surface.

    **`cancellation_check_interval` is deliberately absent as a field.** §12 states it is "not
    configurable to anything coarser — this is a hard requirement, not a tunable", and the only
    way to make that true is to give it no knob at all; `pipeline.py` checks per receipt
    unconditionally. A field defaulted to "per_receipt" would be a knob someone could turn.
    """

    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    debounce: DebounceConfig = field(default_factory=DebounceConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    vendor_match: VendorMatchConfig = field(default_factory=VendorMatchConfig)


#: §14's resolved retention for intermediate stage outputs. Registered as a real Background
#: Workers job (`stage_checkpoint_purge`, owner `execution_core`, in that API's own
#: `KNOWN_JOBS`) rather than left to grow unbounded. Long enough to debug something recently
#: completed, short enough not to accumulate forever.
STAGE_OUTPUT_RETENTION_DAYS: int = 30


@runtime_checkable
class CheckpointStore(Protocol):
    """Persistence's own write path, as seen from here (§6).

    A `Protocol` rather than an import of `core.persistence`: Execution Core orchestrates seven
    other APIs, and a direct import of any of them would make this package unimportable
    wherever that one is not installed (`docs/PRINCIPLES.md` §1.3).
    """

    async def get_checkpoint(
        self, receipt_id: str, stage: ReceiptStage
    ) -> StageCheckpoint | None: ...

    async def write_checkpoint(self, checkpoint: StageCheckpoint) -> None: ...

    async def find_written_by_content_hash(self, content_hash: str) -> StageCheckpoint | None: ...


@runtime_checkable
class AttemptCounter(Protocol):
    """§7's per-receipt-per-stage attempt tally, and the escalation latch beside it.

    `mark_escalated`/`already_escalated` exist because §7's own motivating bug is duplicate
    warnings — see `retry_policy.py`.
    """

    async def get_attempt_count(self, receipt_id: str, stage: ReceiptStage) -> int: ...

    async def increment_attempt_count(self, receipt_id: str, stage: ReceiptStage) -> int: ...

    async def already_escalated(self, receipt_id: str, stage: ReceiptStage) -> bool: ...

    async def mark_escalated(self, receipt_id: str, stage: ReceiptStage) -> None: ...


@runtime_checkable
class ReviewFlagger(Protocol):
    """Review/Flagging's flag-creation surface (§7). Execution Core escalates; it never decides
    what a flag means or who sees it."""

    async def create_flag(
        self, receipt_id: str, flag_type: str, details: FrozenDict | None = None
    ) -> None: ...


@runtime_checkable
class HistorianNarrator(Protocol):
    """Historian's narrative track (§6, and Historian's own deep-dive §5).

    Every stage passes through `run_stage`, so extending that one wrapper gives narrative
    coverage structurally rather than depending on seven other APIs each remembering to call
    Historian themselves.
    """

    async def emit_narrative(
        self, run_id: str, receipt_id: str, stage: ReceiptStage, result: Any
    ) -> None: ...


@runtime_checkable
class WatchdogKicker(Protocol):
    """Health's Watchdog, kicked from inside the loop rather than only around it (§9)."""

    def kick(self, service: str, instance_id: str, version_commit: str = "") -> Any: ...


#: One pipeline stage's actual work — an awaitable with no arguments. The caller closes over
#: whatever that stage needs, which is what lets `run_stage` stay ignorant of seven different
#: APIs' request shapes.
StageCallable = Callable[[], Awaitable[Any]]


__all__ = [
    "ACTIVE_STATES",
    "AttemptCounter",
    "CheckpointStore",
    "ConcurrencyConfig",
    "DebounceConfig",
    "ExecutionConfig",
    "HistorianNarrator",
    "ReceiptOutcome",
    "ReceiptStage",
    "RetryConfig",
    "ReviewFlagger",
    "Run",
    "RunOutcome",
    "RunProgress",
    "RunState",
    "STAGE_OUTPUT_RETENTION_DAYS",
    "STAGE_SEQUENCE",
    "StageAttempt",
    "StageCallable",
    "StageCheckpoint",
    "StageOutcome",
    "TERMINAL_STAGE",
    "VendorCorroborationPolicy",
    "VendorMatchConfig",
    "WatchdogKicker",
    "utcnow",
]

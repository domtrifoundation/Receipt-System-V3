"""The explicit run state machine (`v3-deepdive-10-execution-core-api.md` §3).

§3 does not merely list states, it argues about one of them: `RUNNING` is in the enum for
compatibility and is *not* a fifth distinct state, because a run that is actually processing is
always more precisely `OPEN` or `CLOSING`. Its exact words are that keeping the enum honest
about this "avoids an ambiguous state a future implementer would have to guess the relationship
between."

A comment saying so would not survive contact with a future implementer. The transition table
below is what enforces it: `RUNNING` has no inbound edge from anywhere, so no sequence of legal
transitions can put a run into it, and `ASSIGNABLE_STATES` excludes it so a caller cannot set it
directly either.

The table is data rather than a chain of `if` statements for the same reason Background Workers'
`KNOWN_JOBS` is: a transition rule that lives only in control flow cannot be enumerated, tested
as a whole, or shown to a reviewer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from common.frozen_dict import FrozenDict

from .contracts import ACTIVE_STATES, Run, RunState, utcnow

#: Every legal transition, as data (`docs/PRINCIPLES.md` §2.1.1 — a module-level lookup table is
#: a `FrozenDict`, so one caller's mistaken mutation cannot rewrite the state machine for every
#: run in the process).
#:
#: Two absences are deliberate and are the point of the table:
#:
#: * **Nothing transitions *into* `RUNNING`.** §3's argument, made structural.
#: * **`SHUTTING_DOWN` transitions nowhere.** It is terminal. A cancelled run that could return
#:   to `OPEN` would resume a batch the user explicitly stopped, which is V2's own
#:   keeps-going-after-stop bug (§8) reintroduced one layer up.
ALLOWED_TRANSITIONS: FrozenDict = FrozenDict(
    {
        RunState.WAITING_FOR_TRIGGER: frozenset({RunState.OPEN, RunState.SHUTTING_DOWN}),
        RunState.OPEN: frozenset({RunState.CLOSING, RunState.PAUSED, RunState.SHUTTING_DOWN}),
        RunState.CLOSING: frozenset({RunState.PAUSED, RunState.SHUTTING_DOWN}),
        RunState.PAUSED: frozenset({RunState.OPEN, RunState.CLOSING, RunState.SHUTTING_DOWN}),
        RunState.SHUTTING_DOWN: frozenset(),
        RunState.RUNNING: frozenset(),
    }
)

#: The states a run may actually be set to. `RUNNING` is excluded — see the module docstring.
ASSIGNABLE_STATES: frozenset[RunState] = frozenset(
    state for state in RunState if state is not RunState.RUNNING
)

#: States from which no further transition is possible.
TERMINAL_STATES: frozenset[RunState] = frozenset({RunState.SHUTTING_DOWN})


@dataclass(frozen=True)
class TransitionResult:
    """The outcome of an attempted transition — errors as data (`docs/PRINCIPLES.md` §4.1).

    A rejected transition is an ordinary answer, not an exception. Execution Core's callers
    reach it across gRPC, and "you cannot pause a run that has already shut down" is
    information the caller needs, not a crash it has to catch.
    """

    run: Run
    applied: bool
    error: str = ""


def is_processing(state: RunState) -> bool:
    """Whether a run in this state is actually working.

    This is the honest answer to "is it running?" — `OPEN or CLOSING`, per §3. Callers ask this
    instead of comparing against `RunState.RUNNING`, which is exactly the comparison that would
    always be false.
    """
    return state in ACTIVE_STATES


def can_transition(current: RunState, target: RunState) -> bool:
    """Whether `current -> target` is a legal edge."""
    if target not in ASSIGNABLE_STATES:
        return False
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def transition(run: Run, target: RunState) -> TransitionResult:
    """Move `run` to `target`, or explain why not.

    Stamps `closing_started_at` on the way into `CLOSING` — §5.2 needs the moment finalization
    began, and deriving it later from a log line is how that timestamp goes missing.
    """
    if target not in ASSIGNABLE_STATES:
        return TransitionResult(
            run=run,
            applied=False,
            error=(
                f"{target.value!r} is not an assignable state; a run that is processing is "
                f"{RunState.OPEN.value!r} or {RunState.CLOSING.value!r} (§3)"
            ),
        )
    if run.state is target:
        return TransitionResult(run=run, applied=False, error=f"already {target.value!r}")
    if not can_transition(run.state, target):
        return TransitionResult(
            run=run,
            applied=False,
            error=f"cannot transition from {run.state.value!r} to {target.value!r}",
        )
    if target is RunState.CLOSING and run.closing_started_at is None:
        return TransitionResult(
            run=replace(run, state=target, closing_started_at=utcnow()), applied=True
        )
    return TransitionResult(run=replace(run, state=target), applied=True)


def is_cancelled(run: Run) -> bool:
    """§8's cancellation signal, asked as one question.

    `pipeline.py` checks this at the top of every receipt rather than once per run, which is the
    concrete fix for V2's 156-receipt run that kept going for minutes after a stop request.
    """
    return run.state is RunState.SHUTTING_DOWN


def accepts_new_files(run: Run) -> bool:
    """Whether this run will take more intake (§5.2).

    Only `OPEN` does. A run in `CLOSING` has passed its ceiling, and §5.2 is explicit that the
    ceiling "is a real boundary, not advisory" — a late file starts a new run rather than
    sneaking into a batch that is already finalizing its writes.
    """
    return run.state is RunState.OPEN


__all__ = [
    "ALLOWED_TRANSITIONS",
    "ASSIGNABLE_STATES",
    "TERMINAL_STATES",
    "TransitionResult",
    "accepts_new_files",
    "can_transition",
    "is_cancelled",
    "is_processing",
    "transition",
]

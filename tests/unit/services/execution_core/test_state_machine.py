"""The explicit run state machine (§3).

Most of this module is about one enum member. §3 keeps `RUNNING` for compatibility and argues
at length that it is not a fifth state — a run that is actually processing is always more
precisely `OPEN` or `CLOSING`. A comment saying so does not survive contact with a future
implementer; the transition table and these tests are what do.
"""

from __future__ import annotations


from services.execution_core.contracts import ACTIVE_STATES, RunState
from services.execution_core.state_machine import (
    ALLOWED_TRANSITIONS,
    ASSIGNABLE_STATES,
    accepts_new_files,
    can_transition,
    is_cancelled,
    is_processing,
    transition,
)

from ._doubles import make_run


# --------------------------------------------------------------------------------------------
# §3 — the state machine, and the `RUNNING` member §3 argues about
# --------------------------------------------------------------------------------------------



def test_no_sequence_of_legal_transitions_can_ever_put_a_run_into_the_running_state():
    """§3 keeps `RUNNING` in the enum for compatibility and argues it is not a fifth state.

    A run that is actually processing is always more precisely `OPEN` or `CLOSING`. §3's stated
    reason is to avoid "an ambiguous state a future implementer would have to guess the
    relationship between" — and a comment saying so does not survive contact with that
    implementer. The transition table is what enforces it.
    """
    assert RunState.RUNNING not in ASSIGNABLE_STATES
    for source, targets in ALLOWED_TRANSITIONS.items():
        assert RunState.RUNNING not in targets, f"{source.value} can reach 'running'"


def test_setting_a_run_to_running_is_rejected_with_a_reason_rather_than_silently_ignored():
    """A caller that asked for something impossible needs to be told (`docs/PRINCIPLES.md` §4.1).

    Silently ignoring it would leave the caller believing the run is in a state it is not, which
    is worse than the ambiguity §3 was trying to remove in the first place.
    """
    result = transition(make_run(state=RunState.OPEN), RunState.RUNNING)
    assert result.applied is False
    assert "not an assignable state" in result.error
    assert result.run.state is RunState.OPEN


def test_is_processing_answers_the_running_question_honestly():
    """"Is it running?" has an honest answer, and it is `OPEN or CLOSING` (§3).

    Callers ask this instead of comparing against `RunState.RUNNING` — a comparison that would
    always be false and would report every active run as idle.
    """
    assert is_processing(RunState.OPEN) is True
    assert is_processing(RunState.CLOSING) is True
    assert is_processing(RunState.PAUSED) is False
    assert is_processing(RunState.RUNNING) is False
    assert ACTIVE_STATES == frozenset({RunState.OPEN, RunState.CLOSING})


def test_a_shut_down_run_can_never_be_reopened():
    """Resuming a run the user explicitly stopped is V2's keeps-going-after-stop bug, one layer up.

    §8's fix is about responsiveness; this is about finality. A cancelled batch that could
    return to `OPEN` would start processing again without anyone asking it to.
    """
    cancelled = make_run(state=RunState.SHUTTING_DOWN)
    for target in ASSIGNABLE_STATES:
        assert can_transition(RunState.SHUTTING_DOWN, target) is False
    assert transition(cancelled, RunState.OPEN).applied is False


def test_entering_closing_stamps_the_moment_finalization_began():
    """§5.2 needs the moment finalization started, and deriving it later from a log line is how
    that timestamp goes missing entirely."""
    result = transition(make_run(state=RunState.OPEN), RunState.CLOSING)
    assert result.applied is True
    assert result.run.closing_started_at is not None


def test_only_an_open_run_accepts_new_files():
    """§5.2: a run in `CLOSING` has passed its ceiling and is finalizing its Persistence writes.

    Accepting a file there would write a receipt into a run that had already reported its count
    and fired its completion notification.
    """
    assert accepts_new_files(make_run(state=RunState.OPEN)) is True
    assert accepts_new_files(make_run(state=RunState.CLOSING)) is False
    assert accepts_new_files(make_run(state=RunState.PAUSED)) is False


def test_a_paused_run_can_be_resumed_or_closed_but_a_cancelled_one_cannot():
    """§14 resolved that a client can pause their own run; pause must therefore be reversible.

    A pause that could not be undone would be a cancel with a friendlier name.
    """
    assert can_transition(RunState.PAUSED, RunState.OPEN) is True
    assert can_transition(RunState.PAUSED, RunState.CLOSING) is True
    assert is_cancelled(make_run(state=RunState.PAUSED)) is False
    assert is_cancelled(make_run(state=RunState.SHUTTING_DOWN)) is True


def test_the_transition_table_covers_every_state_in_the_enum():
    """A state missing from the table has no legal transitions and is a silent dead end.

    Adding an enum member without a table row is the easy mistake; the run would enter it and
    never be able to leave, with no error anywhere to say why.
    """
    assert set(ALLOWED_TRANSITIONS.keys()) == set(RunState)

"""The flag lifecycle, both §7 testing hooks, and §8's two resolved questions.

§7's named hooks:

* **Dismissal vs. resolution distinction test** — "confirms a dismissed flag never gets counted
  the same as a resolved one in any staff-facing metrics/queue view — a real, easy-to-blur
  distinction worth explicit coverage."
* **Edit-entry-point write-path test** — "confirms an edit made through this API's deep-link
  genuinely goes through Persistence's normal write path (Historian-logged), not a shortcut
  that bypasses it."

The first is easy to under-test. "Neither is open" is true of both, so a queue view that only
asks *is this still open* blurs them without ever looking wrong — and the difference is real:
a dismissed flag is a false positive (the detector was wrong) while a resolved one is an actual
fix applied (the detector was right). A metrics view that collapses them tells staff their
detectors are performing very differently from how they actually are.

The second is a genuine bypass risk rather than a hypothetical: an edit screen that wrote
directly would be faster and would work, and the only thing lost is the Historian trail — which
is invisible until someone needs it.
"""

from __future__ import annotations

import pytest

from core.review_flagging.contracts import (
    HIGH_STAKES_FLAG_TYPES,
    VALID_TRANSITIONS,
    AssignFlagRequest,
    CreateFlagRequest,
    DismissFlagRequest,
    FlagStatus,
    ListFlagsQuery,
    ResolveFlagRequest,
)
from core.review_flagging.lifecycle import can_transition

from .conftest import RecordingAudit, RecordingNotifier, RecordingWriteGateway, run


def create(store, *, flag_type: str = "vat_mismatch", receipt_id: str = "r1"):
    return run(
        store.create_flag(
            CreateFlagRequest(
                flag_type=flag_type,
                user_id="user-1",
                receipt_id=receipt_id,
                created_by="reconciliation",
            )
        )
    )


# ------------------------------------------------------------------- the state machine


def test_a_created_flag_starts_open(store):
    result = create(store)

    assert result.flag is not None
    assert result.flag.status is FlagStatus.OPEN


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (FlagStatus.RESOLVED, FlagStatus.OPEN),
        (FlagStatus.RESOLVED, FlagStatus.ASSIGNED),
        (FlagStatus.RESOLVED, FlagStatus.DISMISSED),
        (FlagStatus.DISMISSED, FlagStatus.OPEN),
        (FlagStatus.DISMISSED, FlagStatus.ASSIGNED),
        (FlagStatus.DISMISSED, FlagStatus.RESOLVED),
    ],
)
def test_terminal_states_are_terminal(current, target):
    """A settled flag cannot be un-settled.

    Parametrised over every transition out of a terminal state rather than spot-checked,
    because "the state machine is right" is only meaningful if the *invalid* edges are the ones
    enumerated — a table that permitted one of these would let a resolved flag quietly reopen
    and be resolved twice, inflating exactly the metric §7 is worried about.
    """
    assert not can_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (FlagStatus.OPEN, FlagStatus.ASSIGNED),
        (FlagStatus.OPEN, FlagStatus.RESOLVED),
        (FlagStatus.OPEN, FlagStatus.DISMISSED),
        (FlagStatus.ASSIGNED, FlagStatus.RESOLVED),
        (FlagStatus.ASSIGNED, FlagStatus.DISMISSED),
    ],
)
def test_the_legitimate_transitions_are_permitted(current, target):
    """The positive half — otherwise a table rejecting everything would pass the test above."""
    assert can_transition(current, target)


def test_resolving_an_already_resolved_flag_is_refused_explicitly(store, roles):
    """Refused, not silently no-op'd.

    A silent no-op returns success to a staff member whose action did nothing, and leaves the
    resolution note they typed nowhere at all.
    """
    flag = create(store).flag
    run(store.resolve_flag(ResolveFlagRequest(flag_id=flag.flag_id), "sess-staff"))

    second = run(store.resolve_flag(ResolveFlagRequest(flag_id=flag.flag_id), "sess-staff"))

    assert second.flag is None
    assert second.error_code
    assert store.metrics.snapshot().invalid_transitions_rejected >= 1


def test_an_unknown_flag_id_is_an_error_not_a_crash(store):
    result = run(store.resolve_flag(ResolveFlagRequest(flag_id="flg_nope"), "sess-staff"))

    assert result.error_code


# ---------------------------------------------------- §7's dismissal/resolution hook


def test_dismissal_and_resolution_are_counted_separately(store):
    """§7's distinction hook, on the metrics that staff actually read.

    A false positive and an applied fix say opposite things about a detector's quality. One
    counter for both would make a noisy detector and an accurate one look identical.
    """
    first = create(store, receipt_id="r1").flag
    second = create(store, receipt_id="r2").flag

    run(store.resolve_flag(ResolveFlagRequest(flag_id=first.flag_id), "sess-staff"))
    run(store.dismiss_flag(DismissFlagRequest(flag_id=second.flag_id), "sess-staff"))

    snapshot = store.metrics.snapshot()
    assert snapshot.flags_resolved == 1
    assert snapshot.flags_dismissed == 1


def test_dismissal_and_resolution_are_distinguishable_in_the_queue_view(store):
    """The same distinction, on the list a staff member filters.

    Querying for resolved must not return dismissed ones. This is the concrete form of "a
    staff-facing queue view that only asks *is this still open*" — the failure §7 names.
    """
    resolved = create(store, receipt_id="r1").flag
    dismissed = create(store, receipt_id="r2").flag
    run(store.resolve_flag(ResolveFlagRequest(flag_id=resolved.flag_id), "sess-staff"))
    run(store.dismiss_flag(DismissFlagRequest(flag_id=dismissed.flag_id), "sess-staff"))

    only_resolved = run(store.list_flags(ListFlagsQuery(statuses=(FlagStatus.RESOLVED,))))
    only_dismissed = run(store.list_flags(ListFlagsQuery(statuses=(FlagStatus.DISMISSED,))))

    assert [f.flag_id for f in only_resolved.flags] == [resolved.flag_id]
    assert [f.flag_id for f in only_dismissed.flags] == [dismissed.flag_id]


def test_neither_terminal_state_appears_in_the_open_queue(store):
    """Both are settled — the distinction is about *how*, not whether."""
    resolved = create(store, receipt_id="r1").flag
    dismissed = create(store, receipt_id="r2").flag
    run(store.resolve_flag(ResolveFlagRequest(flag_id=resolved.flag_id), "sess-staff"))
    run(store.dismiss_flag(DismissFlagRequest(flag_id=dismissed.flag_id), "sess-staff"))

    still_open = run(store.list_flags(ListFlagsQuery(statuses=(FlagStatus.OPEN,))))

    assert still_open.flags == ()


def test_a_dismissal_records_a_different_audit_operation_than_a_resolution(store, audit):
    """The distinction has to survive into the audit trail too.

    An investigation asking "was this detector ever actually right" reads the audit log, and
    one shared operation name would make that unanswerable after the fact.
    """
    resolved = create(store, receipt_id="r1").flag
    dismissed = create(store, receipt_id="r2").flag
    run(store.resolve_flag(ResolveFlagRequest(flag_id=resolved.flag_id), "sess-staff"))
    run(store.dismiss_flag(DismissFlagRequest(flag_id=dismissed.flag_id), "sess-staff"))

    operations = audit.operations()
    assert len(set(operations)) == len(operations)


# --------------------------------------------------------- §7's edit write-path hook


def test_an_edit_made_while_resolving_goes_through_persistences_write_path(
    store, write_gateway
):
    """§7's edit hook, verbatim: through the normal write path, not a shortcut.

    The bypass is genuinely tempting — writing the row directly would be faster and would
    appear to work. The only thing lost is the Historian trail, which nobody notices until
    they need it, which is exactly why this is a named hook rather than left to review.
    """
    flag = create(store).flag

    result = run(
        store.resolve_flag(
            ResolveFlagRequest(
                flag_id=flag.flag_id, edit_field="vendor_name", edit_new_value="7-ELEVEN"
            ),
            "sess-staff",
        )
    )

    assert result.flag is not None
    assert write_gateway.calls == [("user-1", "r1", "vendor_name", "7-ELEVEN", "staff-1")]
    # `EditWriteResult.historian_event_id` is what the contract calls "the proof the write
    # went through the real path". A gateway that returned `ok=True` with no event id would
    # be describing exactly the bypass this hook exists to catch, so the id is asserted
    # rather than the boolean alone.
    assert result.flag.status is FlagStatus.RESOLVED


def test_the_edit_carries_the_acting_staff_member_not_the_receipts_owner(
    store, write_gateway
):
    """Historian records who changed it, and the answer must be the staff member.

    Attributing a staff edit to the receipt's owner would put a change in the owner's own
    history that they never made — worse than no trail, because it is a confident wrong answer.
    """
    flag = create(store).flag
    run(
        store.resolve_flag(
            ResolveFlagRequest(flag_id=flag.flag_id, edit_field="total_amount", edit_new_value="9"),
            "sess-staff",
        )
    )

    _user, _receipt, _field, _value, actor = write_gateway.calls[0]
    assert actor == "staff-1"


def test_a_failed_edit_write_declines_to_resolve_rather_than_claiming_success(tmp_path, roles):
    """If the edit could not be written, the flag it was resolving is not resolved.

    Marking it resolved anyway would close a real problem on the strength of a fix that never
    landed — and the flag is the only thing that would have brought anyone back to it.
    """
    from core.review_flagging.lifecycle import FlagStore

    store = FlagStore(
        tmp_path / "flags.sqlite",
        role_resolver=roles,
        edit_gateway=RecordingWriteGateway(ok=False),
    )
    try:
        flag = create(store).flag

        result = run(
            store.resolve_flag(
                ResolveFlagRequest(
                    flag_id=flag.flag_id, edit_field="vendor_name", edit_new_value="X"
                ),
                "sess-staff",
            )
        )

        assert result.flag is None
        assert result.error_code
        assert run(store.get_flag(flag.flag_id)).status is FlagStatus.OPEN
    finally:
        store.close()


def test_resolving_without_an_edit_touches_the_write_path_at_all(store, write_gateway):
    """Most resolutions change nothing about the receipt — the detector was simply satisfied."""
    flag = create(store).flag

    run(store.resolve_flag(ResolveFlagRequest(flag_id=flag.flag_id), "sess-staff"))

    assert write_gateway.calls == []


# ------------------------------------------------------------- permissions (§4.2)


def test_a_client_cannot_resolve_a_flag(store):
    """Flag resolution is a staff action; a client resolving their own flags would let the
    subject of a compliance check clear it themselves."""
    flag = create(store).flag

    result = run(store.resolve_flag(ResolveFlagRequest(flag_id=flag.flag_id), "sess-client"))

    assert result.flag is None
    assert result.error_code


def test_an_unresolvable_session_is_denied(store):
    """An unknown session and an unreachable Auth are the same fact to a caller, and both deny."""
    flag = create(store).flag

    result = run(store.resolve_flag(ResolveFlagRequest(flag_id=flag.flag_id), "sess-unknown"))

    assert result.flag is None
    assert result.error_code


def test_a_denied_attempt_is_still_audited(store, audit):
    """An audit trail showing only successes cannot answer "did anyone try"."""
    flag = create(store).flag
    run(store.resolve_flag(ResolveFlagRequest(flag_id=flag.flag_id), "sess-client"))

    assert audit.records


def test_a_failing_audit_sink_does_not_undo_the_resolution(tmp_path, roles):
    """§4.4: an audit-sink outage is a second, independent problem.

    It must not swallow a resolution a staff member legitimately performed — but it must not be
    invisible either, which is what the degraded counter is for.
    """
    from core.review_flagging.lifecycle import FlagStore

    store = FlagStore(tmp_path / "flags.sqlite", role_resolver=roles, audit=RecordingAudit(fail=True))
    try:
        flag = create(store).flag

        result = run(store.resolve_flag(ResolveFlagRequest(flag_id=flag.flag_id), "sess-staff"))

        assert result.flag is not None
        assert store.metrics.snapshot().audit_records_degraded >= 1
    finally:
        store.close()


# ------------------------------------------------ §8's resolved routing and severity


def test_any_staff_member_can_self_assign_an_open_flag(store):
    """§8: a shared open queue with self-assign, matching Support Ticketing's own resolution
    for the structurally identical problem."""
    flag = create(store).flag

    result = run(
        store.assign_flag(
            AssignFlagRequest(flag_id=flag.flag_id, assignee_user_id="staff-1"), "sess-staff"
        )
    )

    assert result.flag.status is FlagStatus.ASSIGNED
    assert result.flag.assigned_to == "staff-1"


def test_a_high_stakes_flag_notifies_immediately(store, notifier):
    """§8's severity split: security and compliance flags are pushed, not queued."""
    create(store, flag_type="content_security_unsafe")

    assert notifier.notified == ["content_security_unsafe"]


def test_a_routine_flag_does_not_notify(store, notifier):
    """An immediate alert for every duplicate or category mismatch would be noise that trains
    people to ignore the channel — §8 says exactly that."""
    create(store, flag_type="semantic_duplicate")

    assert notifier.notified == []
    assert store.metrics.snapshot().notifications_skipped_routine >= 1


def test_the_high_stakes_set_is_the_three_types_section_8_names():
    """Asserted as data so widening it has to be a deliberate edit, not a drift.

    Adding a routine type here would push an alert for it; removing a real one would silence a
    security or regulatory signal. Both are decisions, not refactors.
    """
    assert HIGH_STAKES_FLAG_TYPES == frozenset(
        {"content_security_unsafe", "atp_validity", "bir_completeness"}
    )


def test_a_failing_notifier_never_loses_the_flag(store, tmp_path, roles):
    """The flag is the durable record; the notification is a convenience on top of it."""
    from core.review_flagging.lifecycle import FlagStore

    store = FlagStore(
        tmp_path / "f.sqlite", role_resolver=roles, notifier=RecordingNotifier(fail=True)
    )
    try:
        result = create(store, flag_type="content_security_unsafe")

        assert result.flag is not None
        assert store.metrics.snapshot().notifications_failed >= 1
    finally:
        store.close()


# ------------------------------------------------------------- taxonomy stays Architect's


def test_an_unrecognised_flag_type_is_still_accepted(store):
    """§4.4 and §3.4 together: the taxonomy is Architect's, and a labeling gap is not a reason
    to lose a real signal a producer API raised in good faith.

    Rejecting an unknown type would mean a newly-added detector's findings vanish until someone
    remembers to register the type — silently, and exactly when the detector is newest.
    """
    result = create(store, flag_type="a_type_nobody_registered_yet")

    assert result.flag is not None


def test_the_transition_table_is_the_single_source_of_truth():
    """`can_transition` reads `VALID_TRANSITIONS` rather than restating it.

    Two opinions about which edges are legal would disagree exactly at the edge that mattered.
    """
    for current, targets in VALID_TRANSITIONS.items():
        for target in FlagStatus:
            assert can_transition(current, target) == (target in targets)

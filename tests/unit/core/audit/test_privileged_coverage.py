"""The deep-dive's §7 privileged-action coverage test.

§7 asks for "a structural check against the list, not per-action trust": every action this
project classifies as privileged must actually produce an audit entry, verified by walking
the declared set rather than by trusting that each calling API remembered.

`contracts.PRIVILEGED_ACTIONS` is that list. The tests below assert three separate things:

1. every operation in it round-trips through the writer and lands as a readable event;
2. the specific operations §7 calls out by name are present in it — the check that catches
   the list quietly shrinking;
3. every `ActionType` is reachable from it, so no action type exists that nothing can
   actually record.

**What this test cannot check, stated rather than implied**: whether Auth actually calls this
API when it grants break-glass. That is a cross-API integration concern and belongs in
`tests/integration/` once those APIs exist. This is the half that can be enforced from inside
this package — that the vocabulary is complete and each entry genuinely works.
"""

from __future__ import annotations

import pytest

from core.audit.contracts import PRIVILEGED_ACTIONS, ActionType, AuditQueryFilter

from .conftest import run

#: Named directly in §7's own sentence. If one of these ever stops resolving, the coverage
#: guarantee has been narrowed without anyone deciding to narrow it.
SECTION_7_NAMED_ACTIONS = (
    "break_glass_grant",
    "force_wake",
    "pin_service_version",
    "agent_token_issue",
    "is_group_manager_toggle",
)

#: Actions whose `reason` is mandatory, so the parametrised round-trip supplies one.
_REASON = "recorded by the privileged-action coverage test"


@pytest.mark.parametrize("operation", sorted(PRIVILEGED_ACTIONS))
def test_every_declared_privileged_action_produces_an_entry(writer, query, operation):
    result = run(
        writer.record_action(operation, "staff_1", target_user_id="client_1", reason=_REASON)
    )
    assert result.recorded, f"{operation} produced no audit entry: {result.error_detail}"

    read = run(query.fetch(AuditQueryFilter(), "owner"))
    assert read.total_matching == 1
    assert read.events[0].action_type is PRIVILEGED_ACTIONS[operation]


@pytest.mark.parametrize("operation", SECTION_7_NAMED_ACTIONS)
def test_the_actions_section_7_names_are_all_registered(operation):
    assert operation in PRIVILEGED_ACTIONS, (
        f"{operation!r} is named in the deep-dive's §7 coverage list but is not in "
        f"contracts.PRIVILEGED_ACTIONS — the coverage guarantee has a hole in it"
    )


def test_every_action_type_is_reachable_from_the_operation_table():
    """An `ActionType` no operation maps to is a value that can never be written, which
    means either the table is missing an entry or the enum has dead weight in it."""
    reachable = set(PRIVILEGED_ACTIONS.values())
    unreachable = set(ActionType) - reachable
    assert not unreachable, f"unreachable ActionType members: {sorted(a.value for a in unreachable)}"


def test_operation_names_and_action_values_do_not_collide():
    """The two vocabularies are deliberately distinct — an operation name is what a caller
    passes, an ActionType value is what a ten-year-old row stores. Keeping them visibly
    different stops one silently being used where the other belongs."""
    assert set(PRIVILEGED_ACTIONS) & {a.value for a in ActionType} == set()

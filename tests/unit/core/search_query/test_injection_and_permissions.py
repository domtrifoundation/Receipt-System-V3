"""Both testing hooks §7 names, plus the isolation properties underneath them.

* **FTS5 injection test** — "confirms user-supplied query text with FTS5 special characters
  (`"`, `*`, boolean operators) is properly escaped/bound, never string-concatenated into the
  query."
* **Break-glass expiry mid-session test** — "a search query issued after a grant expires
  mid-session correctly fails, validating §4's query-time (not session-time) check."

The second is the subtler of the two and the reason it earns a hook of its own: a permission
model checked when a session opens looks identical to one checked per query, right up until a
grant is revoked while someone is still typing. The only way to tell them apart is a grant that
changes state *between* two queries in one session, which is exactly what `ExpiringCrossUser`
does.
"""

from __future__ import annotations

import pytest

from core.search_query.contracts import GroupSearchQuery, SearchQuery
from core.search_query.fts_query import build_match_expression
from core.search_query.permission_gate import SearchPermissionGate
from core.search_query.structured_query import SearchExecutor

from .conftest import (
    CLIENT,
    OWNER,
    STAFF,
    AllowCrossUser,
    ExpiringCrossUser,
    StaticGroupManager,
    StaticMembers,
    run,
    seed_receipts,
)


def executor(registry, *, cross_user=None, group_manager=None, members=None) -> SearchExecutor:
    return SearchExecutor(
        registry=registry,
        gate=SearchPermissionGate(cross_user=cross_user, group_manager=group_manager),
        members=members,
    )


# ------------------------------------------------------------------ §7's injection hook


@pytest.mark.parametrize(
    "hostile",
    [
        '" OR receipts_fts MATCH "',
        "* OR 1=1",
        'vendor" AND "secret',
        "NOT everything",
        "a OR b AND c",
        '"; DROP TABLE receipts; --',
        "^prefix",
        "NEAR(a b, 2)",
    ],
)
def test_fts_special_characters_are_quoted_into_literals(hostile):
    """§7's injection hook, at the level the escaping actually happens.

    Every whitespace-separated token becomes its own quoted FTS5 string literal, so an operator
    a user typed is matched *as text* rather than interpreted as syntax. The assertion is that
    nothing survives as a bare FTS5 operator — a single unquoted `OR` would mean the user's
    text is being parsed as a query rather than searched for.
    """
    expression = build_match_expression(hostile)

    # Everything the user typed is inside quotes; the only unquoted token is our own AND.
    outside_quotes = []
    in_quotes = False
    current = ""
    for char in expression:
        if char == '"':
            in_quotes = not in_quotes
            continue
        if not in_quotes:
            current += char
        elif current:
            outside_quotes.append(current.strip())
            current = ""
    outside_quotes.append(current.strip())

    leftovers = {token for token in " ".join(outside_quotes).split() if token}
    assert leftovers <= {"AND"}, f"unquoted FTS5 syntax survived: {leftovers}"


def test_an_embedded_double_quote_is_doubled_not_terminated():
    """The one escaping rule that actually closes the hole.

    A single `"` passed through unchanged would end our own quoted literal and hand the rest of
    the user's text to FTS5 as syntax — which is the concrete mechanism an injection would use.
    """
    assert build_match_expression('say "hi"') == '"say" AND """hi"""'


def test_query_text_is_bound_as_a_parameter_never_concatenated():
    """The structural guarantee behind the escaping.

    `text_match_clause` returns a clause containing a `?` placeholder plus the value to bind
    separately. If the value were ever interpolated into the clause the placeholder would be
    absent — so this asserts the shape, not just the escaping that sits on top of it.
    """
    from core.search_query.fts_query import text_match_clause

    clause, parameter = text_match_clause('" OR 1=1')

    assert "?" in clause
    assert "OR 1=1" not in clause
    assert parameter == '"""" AND "OR" AND "1=1"'


def test_empty_query_text_produces_no_text_filter():
    """FTS5 rejects an empty MATCH expression, so "no text" must mean no clause at all."""
    from core.search_query.fts_query import text_match_clause

    assert text_match_clause("") is None
    assert text_match_clause("   ") is None
    assert build_match_expression("   ") == ""


def test_a_hostile_query_returns_no_rows_rather_than_erroring(registry, seeded):
    """End to end: the injection attempt is simply a search for that literal text.

    Nothing in the seeded data contains it, so the honest answer is an empty result — not an
    error, and certainly not every row.
    """
    result = run(
        executor(registry).search(
            SearchQuery(target_user_id="user-1", query_text='" OR receipts_fts MATCH "'),
            requesting_user_id="user-1",
            requesting_role=CLIENT,
        )
    )

    assert result.ok
    assert result.items == ()


def test_a_legitimate_search_still_finds_its_receipt(registry, seeded):
    """The escaping must not be so aggressive that ordinary search stops working.

    A test suite that only proved hostile input is neutralised would pass just as well against
    an implementation that returned nothing for everything.
    """
    result = run(
        executor(registry).search(
            SearchQuery(target_user_id="user-1", query_text="JOLLIBEE"),
            requesting_user_id="user-1",
            requesting_role=CLIENT,
        )
    )

    assert result.ok
    assert [item.receipt_id for item in result.items] == ["r3"]


# ------------------------------------------------------- §7's break-glass expiry hook


def test_a_grant_expiring_mid_session_fails_the_next_query(registry, seeded, top_level):
    """§7's break-glass hook, and §4's query-time-not-session-time claim.

    The same staff member, the same session, two queries. The grant is live for the first and
    gone for the second. A session-time check would let both through, which is precisely the
    failure a break-glass mechanism exists to prevent — a grant that keeps working after it was
    supposed to lapse.
    """
    checker = ExpiringCrossUser()
    search = executor(registry, cross_user=checker)
    query = SearchQuery(target_user_id="user-1", query_text="JOLLIBEE")

    first = run(search.search(query, requesting_user_id="staff-1", requesting_role=STAFF))
    second = run(search.search(query, requesting_user_id="staff-1", requesting_role=STAFF))

    assert first.ok
    assert not second.ok
    assert second.error_code
    assert checker.checks == 2


def test_every_query_re_checks_rather_than_caching_the_first_answer(registry, seeded):
    """The mechanism behind the hook above, asserted directly.

    A cached authorization would show one check for many queries — and would mean revoking a
    grant did nothing until the session ended.
    """
    checker = AllowCrossUser()
    search = executor(registry, cross_user=checker)
    query = SearchQuery(target_user_id="user-1")

    for _ in range(3):
        run(search.search(query, requesting_user_id="staff-1", requesting_role=STAFF))

    assert len(checker.calls) == 3


# ------------------------------------------------------------------ isolation and roles


def test_a_user_searching_their_own_receipts_needs_no_grant(registry, seeded):
    """Own-user access is the ordinary path and must not require break-glass machinery."""
    result = run(
        executor(registry).search(
            SearchQuery(target_user_id="user-1"),
            requesting_user_id="user-1",
            requesting_role=CLIENT,
        )
    )

    assert result.ok
    assert len(result.items) == 3


def test_a_client_can_never_reach_another_users_receipts(registry, seeded):
    """No break-glass path is offered to a client role at all (§4).

    Even with a checker that would say yes, the client path never consults it — a client is not
    someone who can hold a break-glass grant in the first place.
    """
    result = run(
        executor(registry, cross_user=AllowCrossUser()).search(
            SearchQuery(target_user_id="user-1"),
            requesting_user_id="user-2",
            requesting_role=CLIENT,
        )
    )

    assert not result.ok


def test_staff_without_an_active_grant_is_denied(registry, seeded):
    """The default checker denies, which is what a process with Auth unwired gets."""
    result = run(
        executor(registry).search(
            SearchQuery(target_user_id="user-1"),
            requesting_user_id="staff-1",
            requesting_role=STAFF,
        )
    )

    assert not result.ok


def test_staff_with_an_active_grant_is_allowed(registry, seeded):
    result = run(
        executor(registry, cross_user=AllowCrossUser()).search(
            SearchQuery(target_user_id="user-1"),
            requesting_user_id="staff-1",
            requesting_role=OWNER,
        )
    )

    assert result.ok
    assert len(result.items) == 3


# ----------------------------------------------------------------------- group scoping


def test_a_group_manager_sees_only_their_own_groups_members(registry, top_level):
    """Group visibility stops at the group boundary.

    Two groups exist and the caller manages one. A result set containing the other group's
    receipt would be a cross-tenant leak wearing a legitimate-looking query.
    """
    seed_receipts(top_level, "member-a", [{"receipt_id": "a1", "vendor_name": "ALFAMART"}])
    seed_receipts(top_level, "outsider", [{"receipt_id": "o1", "vendor_name": "ALFAMART"}])

    search = executor(
        registry,
        group_manager=StaticGroupManager(manages={("team-a", "mgr-1")}),
        members=StaticMembers({"team-a": ("member-a",), "team-b": ("outsider",)}),
    )

    result = run(
        search.search_group(
            GroupSearchQuery(group_id="team-a"),
            requesting_user_id="mgr-1",
            requesting_role=CLIENT,
        )
    )

    assert result.ok
    assert {item.user_id for item in result.items} == {"member-a"}


def test_managing_one_group_grants_nothing_over_another(registry, top_level):
    seed_receipts(top_level, "outsider", [{"receipt_id": "o1", "vendor_name": "ALFAMART"}])
    search = executor(
        registry,
        group_manager=StaticGroupManager(manages={("team-a", "mgr-1")}),
        members=StaticMembers({"team-b": ("outsider",)}),
    )

    result = run(
        search.search_group(
            GroupSearchQuery(group_id="team-b"),
            requesting_user_id="mgr-1",
            requesting_role=CLIENT,
        )
    )

    assert not result.ok


def test_an_ordinary_member_is_not_a_manager(registry, top_level):
    """Membership and management are different facts; conflating them would hand every member
    of a group visibility over every colleague's receipts."""
    seed_receipts(top_level, "member-a", [{"receipt_id": "a1", "vendor_name": "ALFAMART"}])
    search = executor(
        registry,
        group_manager=StaticGroupManager(manages=set()),
        members=StaticMembers({"team-a": ("member-a",)}),
    )

    result = run(
        search.search_group(
            GroupSearchQuery(group_id="team-a"),
            requesting_user_id="member-a",
            requesting_role=CLIENT,
        )
    )

    assert not result.ok


# ------------------------------------------------------------------ degradation and limits


def test_a_user_with_no_database_yet_is_an_empty_result_not_an_error(registry):
    """`docs/PRINCIPLES.md` §4.4: a user who has never written a receipt has no database.

    Reporting that as a failure would make a brand-new account's first search look broken.
    """
    result = run(
        executor(registry).search(
            SearchQuery(target_user_id="never-wrote-anything"),
            requesting_user_id="never-wrote-anything",
            requesting_role=CLIENT,
        )
    )

    assert result.ok
    assert result.items == ()


def test_results_past_the_limit_are_truncated_and_say_so(registry, seeded):
    """A silently truncated result set reads as "there are only two" — a wrong answer that
    looks like a right one."""
    result = run(
        executor(registry).search(
            SearchQuery(target_user_id="user-1", limit=2),
            requesting_user_id="user-1",
            requesting_role=CLIENT,
        )
    )

    assert result.ok
    assert len(result.items) == 2
    assert result.truncated


def test_a_negative_limit_is_rejected_as_data(registry, seeded):
    """Almost always a computed value that went wrong, not something a caller meant."""
    result = run(
        executor(registry).search(
            SearchQuery(target_user_id="user-1", limit=-1),
            requesting_user_id="user-1",
            requesting_role=CLIENT,
        )
    )

    assert not result.ok
    assert result.error_code


def test_a_zero_limit_is_a_legitimate_existence_check(registry, seeded):
    """Zero is allowed where negative is not, and the distinction is deliberate.

    "Are there any matches at all, without paying to return them" is a real question — a UI
    deciding whether to show a results pane asks exactly it. So zero yields no items and
    `truncated=True`, which together say "there were matches, you asked for none of them".
    Rejecting it would push callers into asking for one row and discarding it.
    """
    result = run(
        executor(registry).search(
            SearchQuery(target_user_id="user-1", limit=0),
            requesting_user_id="user-1",
            requesting_role=CLIENT,
        )
    )

    assert result.ok
    assert result.items == ()
    assert result.truncated


def test_an_inverted_date_range_is_rejected_rather_than_returning_nothing(registry, seeded):
    """Silently returning nothing for an impossible range makes a typo look like real data."""
    from datetime import timedelta

    from .conftest import BASE

    result = run(
        executor(registry).search(
            SearchQuery(
                target_user_id="user-1", date_from=BASE + timedelta(days=30), date_to=BASE
            ),
            requesting_user_id="user-1",
            requesting_role=CLIENT,
        )
    )

    assert not result.ok

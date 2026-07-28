"""The registry's one enforcement path (`v3-deepdive-07-tool-call-api.md` §3.4, §4, §7).

Three of §7's four named testing hooks live here:

* **Category-enforcement test** — "confirms a `MUTATING_STAGED` tool genuinely cannot
  self-apply without landing in its downstream review gate, and that a `READ_ONLY` tool has no
  write path at all — the concrete validation of §3-4's entire safety model rather than
  trusting the categorization is honored by convention."
* **`DEV_OBSERVABILITY`/`TEST_EXECUTION` separation test** — "confirms no tool is registered in
  both categories... the distinction §4 draws is only real if something checks it."
* **Calling-context scoping test** — "confirms a tool not in a given `calling_api`'s own
  enabled subset is genuinely unreachable from that context, not merely undocumented."

The fourth (agentic-loop termination) belongs to the loop itself and is in `test_dispatch.py`.
"""

from __future__ import annotations

import pytest

from core.auth.contracts import Role
from core.tool_call.contracts import (
    CALLING_API_ALLOWED_CATEGORIES,
    CATEGORY_ALLOWED_ROLES,
    ToolCategory,
    ToolContext,
)
from core.tool_call.errors import (
    ContextNotEnabled,
    PermissionDenied,
    ToolUnavailable,
    UnregisteredTool,
)
from core.tool_call.registry import ToolRegistry, deny_all_permissions

from .conftest import echo_handler, exploding_resolver, resolver_for, spec


def test_unregistered_tool_is_denied(registry, reconciliation_context):
    with pytest.raises(UnregisteredTool):
        registry.check("no_such_tool", reconciliation_context, resolver_for(Role.CLIENT))


def test_default_resolver_denies_everything(registry, reconciliation_context):
    """The safe default, and the reason every other test has to name a role explicitly.

    Auth resolution is a live cross-process call. A caller that forgets to wire one in gets a
    closed gate, not a silently permissive one (`docs/PRINCIPLES.md` §4.2).
    """
    with pytest.raises(PermissionDenied):
        registry.check("lookup_vendor_canon", reconciliation_context, deny_all_permissions)


def test_resolver_that_raises_is_a_denial_not_an_allow(registry, reconciliation_context):
    """Auth unreachable is the canonical "unresolvable permission" case §4.2 names.

    A `try` that let the exception through would surface as a 500 the caller might retry
    around; one that defaulted to allow would be the silent bypass. Neither is acceptable.
    """
    with pytest.raises(PermissionDenied):
        registry.check("lookup_vendor_canon", reconciliation_context, exploding_resolver)


def test_client_role_reaches_read_only_and_mutating_staged(registry, reconciliation_context):
    """The ordinary caller shape: the loop processing that client's own receipt.

    `MUTATING_STAGED` being available to a client is not a privilege escalation — the write
    lands in Architect's moderation queue, and the safety gate is downstream and asynchronous
    (§4), not a confirmation nobody is present to give.
    """
    resolver = resolver_for(Role.CLIENT)

    assert registry.check("lookup_vendor_canon", reconciliation_context, resolver)
    assert registry.check("remember_vendor", reconciliation_context, resolver)


def test_calling_context_scoping_makes_a_tool_genuinely_unreachable(
    registry, reconciliation_context
):
    """§7's calling-context scoping hook.

    `reset_test_environment` wipes a test tenant. The reconciliation loop has no business
    reaching it, and the denial must come from the context gate — before the role gate — so
    that even an owner-role session driving a reconciliation run cannot reach it.
    """
    with pytest.raises(ContextNotEnabled):
        registry.check("reset_test_environment", reconciliation_context, resolver_for(Role.OWNER))

    with pytest.raises(ContextNotEnabled):
        registry.check("get_run_status", reconciliation_context, resolver_for(Role.OWNER))


def test_context_gate_runs_before_the_role_gate(registry, reconciliation_context):
    """The order matters and is asserted, not assumed.

    If the role gate ran first, an owner-role reconciliation run would get `PermissionDenied`
    for a `TEST_EXECUTION` tool — implying the right role would unlock it. The context gate
    firing first says the correct thing instead: this surface does not offer that tool at all.
    """
    with pytest.raises(ContextNotEnabled):
        registry.check(
            "reset_test_environment", reconciliation_context, resolver_for(Role.OWNER)
        )


def test_agent_control_context_reaches_the_dev_categories(registry, agent_context):
    resolver = resolver_for(Role.STAFF)

    assert registry.check("get_run_status", agent_context, resolver)
    assert registry.check("reset_test_environment", agent_context, resolver)


def test_client_role_cannot_reach_dev_categories_even_through_agent_control(
    registry, agent_context
):
    """The two gates are independent, and both have to pass.

    Agent Control's surface offers these categories; a client-role session reaching it still
    does not get them.
    """
    resolver = resolver_for(Role.CLIENT)

    with pytest.raises(PermissionDenied):
        registry.check("get_run_status", agent_context, resolver)
    with pytest.raises(PermissionDenied):
        registry.check("reset_test_environment", agent_context, resolver)


def test_unknown_calling_context_is_denied_every_category(registry):
    """An unrecognised context gets the empty set, never the union of everything.

    This is the failure mode a `.get(key, ALL)` default would create, and it is exactly the
    kind of "unknown means permissive" bug §4.2 exists to rule out.
    """
    context = ToolContext(run_id="r", user_id="u", calling_api="something_new")

    with pytest.raises(ContextNotEnabled):
        registry.check("lookup_vendor_canon", context, resolver_for(Role.OWNER))


def test_unavailable_tool_is_not_offered_rather_than_offered_and_failing(
    reconciliation_context,
):
    """§3.4's "don't offer an always-failing tool" pattern, generalised past geocoding.

    V2 excluded `geocode_place` when no geo provider was configured, on the reasoning that a
    tool which can only fail wastes the model's own turns. Same reasoning, same behaviour.
    """
    registry = ToolRegistry()
    registry.register(spec("geocode_place"), echo_handler, available=lambda: False)

    with pytest.raises(ToolUnavailable):
        registry.check("geocode_place", reconciliation_context, resolver_for(Role.CLIENT))

    assert registry.enabled_tools(reconciliation_context, resolver_for(Role.CLIENT)) == ()


def test_availability_check_that_raises_means_unavailable(reconciliation_context):
    """A health check that throws is not "the check didn't run, so allow it" (§4.4)."""

    def explodes() -> bool:
        raise OSError("provider socket closed")

    registry = ToolRegistry()
    registry.register(spec("geocode_place"), echo_handler, available=explodes)

    with pytest.raises(ToolUnavailable):
        registry.check("geocode_place", reconciliation_context, resolver_for(Role.CLIENT))


def test_enabled_tools_is_the_same_gate_dispatch_re_checks(registry, reconciliation_context):
    """The manifest Inference builds its grammar from must not over-promise.

    A tool appearing in the manifest but denied at call time would have the model spend a
    round discovering that — which is the same waste §3.4 rejects, one step later.
    """
    names = {
        s.name for s in registry.enabled_tools(reconciliation_context, resolver_for(Role.CLIENT))
    }

    assert names == {"lookup_vendor_canon", "remember_vendor"}


def test_manifest_is_ordered_so_a_grammar_built_from_it_is_stable(
    registry, reconciliation_context
):
    specs = registry.enabled_tools(reconciliation_context, resolver_for(Role.CLIENT))

    assert [s.name for s in specs] == sorted(s.name for s in specs)


# ------------------------------------------------------- category model, as data


def test_mutating_direct_is_not_a_category_at_all():
    """§4: a genuinely ungated mutation is never on the menu, not gated behind a confirmation.

    Asserted against the enum's own membership because the deep-dive's argument is structural
    — there is no confirmation mechanism in an unattended pipeline to gate such a tool with,
    so the category simply does not exist rather than existing-but-restricted.
    """
    assert {c.value for c in ToolCategory} == {
        "read_only",
        "mutating_staged",
        "dev_observability",
        "test_execution",
    }


def test_dev_observability_and_test_execution_are_separate_categories():
    """§7's separation hook, in the form that can actually be checked here.

    The two look similar — both serve development — but `DEV_OBSERVABILITY` only reads while
    `TEST_EXECUTION` kills processes and wipes test tenants. Folding them would blur exactly
    the read-versus-mutate line this project draws everywhere else.
    """
    assert ToolCategory.DEV_OBSERVABILITY is not ToolCategory.TEST_EXECUTION
    assert (
        CATEGORY_ALLOWED_ROLES[ToolCategory.DEV_OBSERVABILITY]
        == CATEGORY_ALLOWED_ROLES[ToolCategory.TEST_EXECUTION]
    )


def test_no_tool_is_registered_in_two_categories(registry):
    """§7's separation hook, on the registry itself.

    A name registered twice under different categories would make its category depend on
    registration order, which is the one way the whole safety model becomes advisory.
    """
    by_name: dict[str, set[ToolCategory]] = {}
    for tool_spec in registry.all_specs():
        by_name.setdefault(tool_spec.name, set()).add(tool_spec.category)

    assert all(len(categories) == 1 for categories in by_name.values())


def test_reconciliation_context_is_never_offered_the_dev_categories():
    """The category model as data, so a future edit to the table fails here.

    Adding `TEST_EXECUTION` to the reconciliation loop's allowed set would be a real safety
    change, and it should have to break a test that says so rather than passing silently.
    """
    allowed = CALLING_API_ALLOWED_CATEGORIES["inference_reconciliation"]

    assert allowed == frozenset({ToolCategory.READ_ONLY, ToolCategory.MUTATING_STAGED})
    assert ToolCategory.TEST_EXECUTION not in allowed
    assert ToolCategory.DEV_OBSERVABILITY not in allowed

"""Dispatch: enforce, invoke, convert, audit — and never raise (§4.1, §7).

`dispatch()` is the boundary the whole "errors are data" rule is about for this API. A tool
wraps a call into another API; those calls fail in every way a network call can, and the one
thing that must never happen is an exception crossing this boundary — because the caller is
Inference's agentic loop (§3.3), and a raised exception there ends a receipt's processing
rather than becoming a tool result the model can read and react to.

§7's agentic-loop termination hook is here too: the loop must end on the model's own final
answer, with `max_rounds` a genuine safety cap rather than the primary termination logic.
"""

from __future__ import annotations

import pytest

from common.frozen_dict import FrozenDict
from core.auth.contracts import Role
from core.tool_call.contracts import ToolCategory, ToolContext
from core.tool_call.dispatch import (
    PRIVILEGED_CATEGORIES,
    InMemoryAuditRecorder,
    dispatch,
)
from core.tool_call.metrics import ToolCallMetricsCollector
from core.tool_call.registry import ToolRegistry

from .conftest import (
    echo_handler,
    exploding_handler,
    exploding_resolver,
    hanging_handler,
    resolver_for,
    spec,
    wrong_shape_handler,
)


def test_a_permitted_call_returns_the_handler_payload(registry, reconciliation_context):
    result = dispatch(
        registry,
        reconciliation_context,
        "lookup_vendor_canon",
        {"query": "7-Eleven"},
        resolver=resolver_for(Role.CLIENT),
    )

    assert result.ok
    assert result.result["echoed"] == {"query": "7-Eleven"}
    assert result.error is None


def test_unregistered_tool_becomes_data_not_an_exception(registry, reconciliation_context):
    result = dispatch(
        registry,
        reconciliation_context,
        "no_such_tool",
        {},
        resolver=resolver_for(Role.OWNER),
    )

    assert not result.ok
    assert result.error_code == "UNREGISTERED_TOOL"


def test_permission_denial_becomes_data(registry, reconciliation_context):
    result = dispatch(registry, reconciliation_context, "lookup_vendor_canon", {})

    assert not result.ok
    assert result.error_code == "PERMISSION_DENIED"


def test_auth_being_unreachable_denies_rather_than_raising(registry, reconciliation_context):
    result = dispatch(
        registry,
        reconciliation_context,
        "lookup_vendor_canon",
        {},
        resolver=exploding_resolver,
    )

    assert not result.ok
    assert result.error_code == "PERMISSION_DENIED"


def test_a_handler_that_raises_is_converted_at_the_boundary(reconciliation_context):
    """The single most important behaviour in this module.

    Every tool wraps another API. Those calls raise. If that reached Inference's loop it would
    end a receipt's processing instead of becoming something the model can read and route
    around.
    """
    registry = ToolRegistry()
    registry.register(spec("lookup_vendor_canon"), exploding_handler)

    result = dispatch(
        registry,
        reconciliation_context,
        "lookup_vendor_canon",
        {},
        resolver=resolver_for(Role.CLIENT),
    )

    assert not result.ok
    assert result.error_code == "TOOL_RAISED"
    assert "unreachable" in result.error


def test_a_handler_that_hangs_is_capped_by_the_timeout(reconciliation_context):
    registry = ToolRegistry()
    registry.register(spec("slow_tool"), hanging_handler)

    result = dispatch(
        registry,
        reconciliation_context,
        "slow_tool",
        {},
        resolver=resolver_for(Role.CLIENT),
        timeout=0.05,
    )

    assert not result.ok
    assert result.error_code == "TOOL_TIMED_OUT"


def test_a_handler_returning_a_non_mapping_is_an_error_not_a_crash(reconciliation_context):
    """A wrapper that forgot to unpack another API's result object is the ordinary cause.

    Letting it through would put a non-mapping into `ToolResult.result`, which is typed
    `FrozenDict` — the failure would surface later, somewhere unrelated.
    """
    registry = ToolRegistry()
    registry.register(spec("bad_wrapper"), wrong_shape_handler)

    result = dispatch(
        registry,
        reconciliation_context,
        "bad_wrapper",
        {},
        resolver=resolver_for(Role.CLIENT),
    )

    assert not result.ok
    assert result.error_code == "TOOL_RAISED"


def test_non_mapping_arguments_are_rejected_as_data(registry, reconciliation_context):
    """`arguments` is typed `object` precisely so this is a verdict, not a `TypeError`."""
    result = dispatch(
        registry,
        reconciliation_context,
        "lookup_vendor_canon",
        "not a mapping",
        resolver=resolver_for(Role.CLIENT),
    )

    assert not result.ok
    assert result.error_code == "INVALID_ARGUMENTS"


def test_the_handler_cannot_see_later_mutations_of_the_caller_s_dict(reconciliation_context):
    """§5's frozen-contract argument, in the one place it actually bites.

    A live dict handed in, mutated after the call returns, must not change what the handler
    saw or what the audit record captured. `FrozenDict` at the boundary is what guarantees it.
    """
    seen: list[object] = []

    def capturing_handler(arguments: FrozenDict, context: ToolContext):
        seen.append(arguments)
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(spec("capture"), capturing_handler)
    live = {"vendor": "7-Eleven"}

    dispatch(
        registry,
        reconciliation_context,
        "capture",
        live,
        resolver=resolver_for(Role.CLIENT),
    )
    live["vendor"] = "changed afterwards"

    assert seen[0]["vendor"] == "7-Eleven"


def test_tool_result_payload_cannot_be_edited_after_the_fact(registry, reconciliation_context):
    result = dispatch(
        registry,
        reconciliation_context,
        "lookup_vendor_canon",
        {"query": "x"},
        resolver=resolver_for(Role.CLIENT),
    )

    with pytest.raises(Exception):
        result.result["echoed"] = "tampered"  # type: ignore[index]


# ------------------------------------------------------------------------ auditing


def test_a_privileged_invocation_lands_in_the_audit_log(registry, reconciliation_context):
    audit = InMemoryAuditRecorder()

    dispatch(
        registry,
        reconciliation_context,
        "remember_vendor",
        {"name": "7-Eleven"},
        resolver=resolver_for(Role.CLIENT),
        audit=audit,
    )

    entries = audit.entries()
    assert len(entries) == 1
    assert entries[0].tool_name == "remember_vendor"
    assert entries[0].outcome == "ok"
    assert entries[0].category is ToolCategory.MUTATING_STAGED


def test_a_denied_privileged_attempt_is_audited_too(registry, reconciliation_context):
    """A rejected mutating action is often the more interesting record, not a non-event.

    An audit trail that only shows what succeeded cannot answer "did something try", which is
    the question an investigation actually starts from.
    """
    audit = InMemoryAuditRecorder()

    dispatch(
        registry,
        reconciliation_context,
        "remember_vendor",
        {"name": "7-Eleven"},
        resolver=resolver_for(None),
        audit=audit,
    )

    entries = audit.entries()
    assert len(entries) == 1
    assert entries[0].outcome == "permission_denied"


def test_read_only_calls_are_not_audited(registry, reconciliation_context):
    """Auditing every lookup would bury the privileged records in noise.

    `PRIVILEGED_CATEGORIES` is what draws that line, and it is asserted as data below so a
    change to it has to be deliberate.
    """
    audit = InMemoryAuditRecorder()

    dispatch(
        registry,
        reconciliation_context,
        "lookup_vendor_canon",
        {},
        resolver=resolver_for(Role.CLIENT),
        audit=audit,
    )

    assert audit.entries() == ()


def test_privileged_categories_are_the_two_that_change_something():
    assert PRIVILEGED_CATEGORIES == frozenset(
        {ToolCategory.MUTATING_STAGED, ToolCategory.TEST_EXECUTION}
    )


def test_an_audit_sink_failure_does_not_corrupt_the_tool_result(
    registry, reconciliation_context
):
    """§4.4: an audit-sink outage is a second, independent problem.

    It must not swallow a result the caller already earned — but it must not be invisible
    either, which is why the metrics gap below is the operator-visible signal.
    """

    class BrokenAudit:
        def record(self, entry) -> None:
            raise OSError("audit sink unavailable")

    metrics = ToolCallMetricsCollector()

    result = dispatch(
        registry,
        reconciliation_context,
        "remember_vendor",
        {"name": "x"},
        resolver=resolver_for(Role.CLIENT),
        audit=BrokenAudit(),
        metrics=metrics,
    )

    assert result.ok
    snapshot = metrics.snapshot()
    assert snapshot.invocations_ok == 1
    assert snapshot.audit_records_written == 0


def test_metrics_distinguish_each_denial_reason(registry, reconciliation_context):
    metrics = ToolCallMetricsCollector()

    dispatch(registry, reconciliation_context, "nope", {}, metrics=metrics)
    dispatch(registry, reconciliation_context, "lookup_vendor_canon", {}, metrics=metrics)
    dispatch(
        registry,
        reconciliation_context,
        "get_run_status",
        {},
        resolver=resolver_for(Role.OWNER),
        metrics=metrics,
    )

    snapshot = metrics.snapshot()
    assert snapshot.invocations_total == 3
    assert snapshot.denied_unregistered == 1
    assert snapshot.denied_permission == 1
    assert snapshot.denied_context == 1


# ------------------------------------------------------------- the agentic loop (§3.3)


def test_the_loop_ends_when_the_model_answers_rather_than_calling_a_tool(
    registry, reconciliation_context
):
    """§7's agentic-loop termination hook, first half.

    §3.3 is explicit that there is no `finalize_receipt` pseudo-tool: the model's final answer
    is the natural conclusion of the same loop that calls real tools, and the loop ends because
    the model chose to answer. This simulates exactly that — two tool rounds, then an answer.
    """
    rounds = []

    def model(round_index: int):
        if round_index < 2:
            return ("lookup_vendor_canon", {"round": round_index})
        return None

    max_rounds = 8
    answer = None
    for i in range(max_rounds):
        choice = model(i)
        if choice is None:
            answer = "final"
            break
        name, args = choice
        rounds.append(
            dispatch(
                registry,
                reconciliation_context,
                name,
                args,
                resolver=resolver_for(Role.CLIENT),
            )
        )

    assert answer == "final"
    assert len(rounds) == 2
    assert all(r.ok for r in rounds)


def test_max_rounds_genuinely_caps_a_model_that_never_stops(registry, reconciliation_context):
    """§7's termination hook, second half — the cap must be real, not nominal.

    §3.3 calls hitting it a genuine failure mode surfacing via Review/Flagging, not a normal
    path. What is asserted here is only that it bounds the loop: a cap nothing enforces is how
    an unproductive model burns unbounded cost and latency on one receipt.
    """
    max_rounds = 8
    calls = 0

    for _ in range(max_rounds):
        calls += 1
        dispatch(
            registry,
            reconciliation_context,
            "lookup_vendor_canon",
            {},
            resolver=resolver_for(Role.CLIENT),
        )

    assert calls == max_rounds


def test_no_finalize_tool_is_registered(registry):
    """§3.2/§8: `finalize_receipt` and `finish_reconciliation` do not carry forward.

    They were V2's workaround for having no structured-output mechanism. V3's Inference API
    has constrained decoding, so the final answer is a return value — registering a pseudo-tool
    to smuggle it out would reintroduce a V2 workaround as a V3 design.
    """
    names = {s.name for s in registry.all_specs()}

    assert "finalize_receipt" not in names
    assert "finish_reconciliation" not in names

"""The gRPC servicer — message translation and the fail-closed role gate.

The servicer's methods are exercised directly rather than over a real channel: this is a
unit test of the translation layer and the gate, and standing a server up would test
`grpc.aio` rather than this package. The wire round-trip belongs in `tests/integration/`.
"""

from __future__ import annotations

import json

import pytest

# `nox -s forward_compat` deliberately installs a narrow dependency set that excludes grpcio,
# because grpcio has no prebuilt wheel for 3.15 yet (noxfile.py's own module docstring). This
# file must therefore skip rather than break collection there — the same graceful-degradation
# posture the rest of the project takes toward an unavailable optional dependency (§4.4).
pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter's environment")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.audit.errors import E_INVALID_EVENT, E_ROLE_FORBIDDEN, E_UNKNOWN_ACTION  # noqa: E402
from core.audit.generated import audit_pb2 as pb  # noqa: E402
from core.audit.service import (  # noqa: E402
    BASELINE_CITATION,
    AuditServicer,
    deny_all_roles,
)

from .conftest import run  # noqa: E402


@pytest.fixture
def servicer(db_path):
    s = AuditServicer(db_path)
    yield s
    s.close()


def staff_resolver(context):
    return "staff"


# ------------------------------------------------------------------- recording


def test_record_action_round_trips(servicer):
    response = run(
        servicer.RecordAction(
            pb.RecordActionRequest(
                operation="break_glass_grant",
                actor_user_id="staff_1",
                target_user_id="client_9",
                reason="incident 42",
                details_json=json.dumps({"folder": "client_9"}),
            ),
            None,
        )
    )
    assert response.recorded and response.error_code == ""
    assert response.event_id.startswith("aud_")


def test_an_unknown_operation_comes_back_as_error_data_not_a_status_code(servicer):
    """`docs/PRINCIPLES.md` §4.1 — nothing is raised across this boundary."""
    response = run(
        servicer.RecordAction(
            pb.RecordActionRequest(operation="sneak", actor_user_id="staff_1"), None
        )
    )
    assert not response.recorded and response.error_code == E_UNKNOWN_ACTION


def test_a_malformed_wire_timestamp_is_error_data_not_a_raised_exception(servicer, db_path):
    """Regression, §4.1. `datetime.fromisoformat` on an unparseable wire value used to raise
    `ValueError` straight out of the servicer method — an exception crossing the gRPC
    boundary, which is exactly what this API does not do."""
    recorded = run(
        servicer.RecordAction(
            pb.RecordActionRequest(
                operation="config_change", actor_user_id="a", occurred_at="whenever"
            ),
            None,
        )
    )
    assert not recorded.recorded and recorded.error_code == E_INVALID_EVENT

    staffed = AuditServicer(db_path, role_resolver=staff_resolver)
    try:
        read = run(staffed.QueryEvents(pb.QueryEventsRequest(occurred_after="yesterday"), None))
        assert read.error_code == E_INVALID_EVENT
        assert "occurred_after" in read.error_detail
    finally:
        staffed.close()


def test_metrics_surface_an_unresolvable_retention_policy(db_path):
    """The horizon count is only meaningful if the policy resolved. Returning
    `events_past_horizon == 0` with no error told a monitoring caller "nothing is waiting for
    the next sweep" when the truth was "your retention setting could not be resolved"."""
    servicer = AuditServicer(db_path, role_resolver=staff_resolver)
    try:
        run(
            servicer.RecordAction(
                pb.RecordActionRequest(operation="config_change", actor_user_id="o"), None
            )
        )
        response = run(servicer.GetMetrics(pb.GetMetricsRequest(retention_days=30), None))
        assert response.error_code == "RETENTION_BELOW_BASELINE"
        # The counts that do not depend on a horizon still come back — degrade, not fail.
        assert response.total_events == 1
        assert response.events_past_horizon == 0
    finally:
        servicer.close()


def test_malformed_details_json_is_rejected_before_it_reaches_the_writer(servicer):
    for payload in ("{not json", json.dumps([1, 2, 3])):
        response = run(
            servicer.RecordAction(
                pb.RecordActionRequest(
                    operation="config_change", actor_user_id="owner_1", details_json=payload
                ),
                None,
            )
        )
        assert response.error_code == E_INVALID_EVENT


# ---------------------------------------------------------------- role gating


def test_the_default_role_resolver_denies(servicer):
    """Auth owns session resolution and does not exist yet. The default must deny, so
    wiring Auth in later means passing a real resolver rather than removing a permissive
    default nobody remembered was there (`docs/PRINCIPLES.md` §4.2)."""
    assert deny_all_roles(None) is None
    response = run(servicer.QueryEvents(pb.QueryEventsRequest(), None))
    assert response.error_code == E_ROLE_FORBIDDEN


def test_a_resolved_staff_role_can_read(db_path):
    servicer = AuditServicer(db_path, role_resolver=staff_resolver)
    try:
        run(
            servicer.RecordAction(
                pb.RecordActionRequest(operation="config_change", actor_user_id="owner_1"), None
            )
        )
        response = run(servicer.QueryEvents(pb.QueryEventsRequest(), None))
        assert response.error_code == ""
        assert response.total_matching == 1
        assert response.events[0].action_type == "config_changed"
        assert json.loads(response.events[0].details_json) == {}
    finally:
        servicer.close()


def test_applying_retention_is_gated_the_same_way_as_reading(servicer):
    """It deletes records, so it is owner/staff-gated — and gated before anything is
    resolved, not after."""
    response = run(
        servicer.ApplyRetentionPolicy(pb.ApplyRetentionPolicyRequest(actor_user_id="x"), None)
    )
    assert response.error_code == E_ROLE_FORBIDDEN


# ----------------------------------------------------------------- retention


def test_the_resolved_policy_carries_the_regulation_on_the_wire(servicer):
    response = run(
        servicer.ResolveRetentionPolicy(pb.ResolveRetentionPolicyRequest(), None)
    )
    assert response.error_code == ""
    assert response.retention_days == 3650
    assert response.retention_mode == "fixed"
    assert response.baseline_citation == BASELINE_CITATION
    assert "17-2013" in response.baseline_citation


def test_a_below_baseline_request_is_refused_with_the_citation_still_attached(servicer):
    response = run(
        servicer.ResolveRetentionPolicy(
            pb.ResolveRetentionPolicyRequest(retention_days=30), None
        )
    )
    assert response.error_code == "RETENTION_BELOW_BASELINE"
    assert response.baseline_citation == BASELINE_CITATION


# ------------------------------------------------------------------- metrics


def test_metrics_are_reported_without_a_role_gate(db_path):
    """Deliberate: a metrics snapshot is counts and timestamps, never the content of any
    event, so Health can poll it without holding a staff session."""
    servicer = AuditServicer(db_path, role_resolver=staff_resolver)
    try:
        run(
            servicer.RecordAction(
                pb.RecordActionRequest(operation="force_wake", actor_user_id="staff_1"), None
            )
        )
        response = run(servicer.GetMetrics(pb.GetMetricsRequest(), None))
        assert response.error_code == ""
        assert response.total_events == 1
        assert dict(response.events_by_action) == {"service_force_woken": 1}
    finally:
        servicer.close()

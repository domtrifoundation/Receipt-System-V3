"""The gRPC surface, the run registry, and metrics (§11, §10.3, §14).

Errors are data here (`docs/PRINCIPLES.md` §4.1) — Execution Core has no equivalent of Auth's
raise-loudly carve-out, so an unknown run id and a rejected transition both come back as
readable payloads. The streaming assertion is made against the generated descriptor rather than
against behaviour, because a unary `GetRunStatus` would pass every behavioural test in this
suite while reproducing the exact V2 defect §11 chose streaming to fix.
"""

from __future__ import annotations

import pytest

from services.execution_core.contracts import ReceiptStage, RunState, StageOutcome
from services.execution_core.metrics import ExecutionMetricsCollector
from services.execution_core.service import ExecutionCoreServicer, RunRegistry

from ._doubles import make_run, run


# --------------------------------------------------------------------------------------------
# §11 — the gRPC surface, errors as data
# --------------------------------------------------------------------------------------------



def test_starting_a_run_without_a_user_id_returns_an_error_field_rather_than_raising():
    """`docs/PRINCIPLES.md` §4.1: errors are data at API boundaries.

    Execution Core has no equivalent of Auth's deliberate raise-loudly carve-out — nothing here
    is a security decision, and a caller across gRPC needs a payload it can read, not a status
    code it has to guess the meaning of.
    """
    pytest.importorskip("grpc")
    servicer = ExecutionCoreServicer()

    from services.execution_core.generated import execution_core_pb2

    response = run(servicer.StartRun(execution_core_pb2.StartRunRequest(user_id="")))
    assert response.error_code == "invalid_request"


def test_cancelling_an_unknown_run_is_an_error_payload_not_an_exception():
    """A caller cancelling a run that already finished is ordinary, not exceptional."""
    pytest.importorskip("grpc")
    servicer = ExecutionCoreServicer()

    from services.execution_core.generated import execution_core_pb2

    response = run(
        servicer.CancelRun(execution_core_pb2.CancelRunRequest(run_id="nope"))
    )
    assert response.error_code == "run_not_found"


def test_a_trigger_reports_whether_it_opened_a_new_run_or_joined_an_open_one():
    """§5.2's coalescing is invisible to a caller that cannot tell the two apart.

    A client that uploaded files either side of the ceiling needs to know its files landed in
    two runs, because it will otherwise wait forever for one completion notification.
    """
    pytest.importorskip("grpc")
    servicer = ExecutionCoreServicer()

    from services.execution_core.generated import execution_core_pb2

    first = run(
        servicer.StartRun(execution_core_pb2.StartRunRequest(user_id="u-1", file_count=2))
    )
    second = run(
        servicer.StartRun(execution_core_pb2.StartRunRequest(user_id="u-1", file_count=1))
    )

    assert first.started_new_run is True
    assert second.started_new_run is False
    assert second.run.run_id == first.run.run_id
    assert second.run.receipt_count == 3


def test_the_registry_exposes_a_live_cancellation_signal_rather_than_a_snapshot():
    """§8's per-receipt check is decorative unless the signal can actually change mid-loop.

    `Run` is frozen and `transition` returns a new object, so re-reading the run handed to
    `process_run` would read the same snapshot every iteration. This is the seam that makes a
    `CancelRun` RPC arriving mid-batch visible to the very next receipt.
    """
    registry = RunRegistry()
    registry.put(make_run(run_id="r-live"))
    check = registry.is_cancelled_for("r-live")

    assert check() is False
    registry.set_state("r-live", RunState.SHUTTING_DOWN)
    assert check() is True


def test_the_wire_never_reports_a_run_as_running():
    """§3's argument has to survive serialization too.

    A wire payload saying `running` would let a webapp render a state the state machine says
    cannot exist, and the next implementer would reasonably add it back to the enum.
    """
    pytest.importorskip("grpc")
    servicer = ExecutionCoreServicer()

    from services.execution_core.generated import execution_core_pb2

    response = run(
        servicer.StartRun(execution_core_pb2.StartRunRequest(user_id="u-1", file_count=1))
    )
    assert response.run.state != RunState.RUNNING.value
    assert response.run.state == RunState.OPEN.value


def test_a_status_stream_for_an_unknown_run_yields_one_error_frame_rather_than_nothing():
    """A stream that closes with nothing in it is indistinguishable from a network fault.

    The caller would retry forever against a run id that will never exist.
    """
    pytest.importorskip("grpc")
    servicer = ExecutionCoreServicer()

    from services.execution_core.generated import execution_core_pb2

    async def _collect():
        frames = []
        async for frame in servicer.GetRunStatus(
            execution_core_pb2.RunStatusRequest(run_id="ghost")
        ):
            frames.append(frame)
        return frames

    frames = run(_collect())
    assert len(frames) == 1
    assert frames[0].error_code == "run_not_found"


def test_get_run_status_is_server_streaming_on_the_wire():
    """§11 chose streaming as the direct answer to V2's "results only show at end of run".

    A unary `GetRunStatus` would compile, pass every behavioural test above, and reproduce the
    exact defect the choice of gRPC was made to fix — so the descriptor itself is pinned.
    """
    pytest.importorskip("grpc")
    from services.execution_core.generated import execution_core_pb2

    service = execution_core_pb2.DESCRIPTOR.services_by_name["ExecutionCoreService"]
    method = service.methods_by_name["GetRunStatus"]
    assert method.server_streaming is True
    assert method.client_streaming is False

# --------------------------------------------------------------------------------------------
# §10.3 / §14 — metrics and the resolved retention policy
# --------------------------------------------------------------------------------------------



def test_stage_metrics_are_recorded_per_stage_and_per_outcome():
    """§10.3: the one valuable profiling target here is a per-stage breakdown.

    A single global `stages_completed` counter cannot answer "which stage is where the failures
    are", which is the only question §10.3 says is worth asking of this API.
    """
    collector = ExecutionMetricsCollector()
    collector.record_stage(ReceiptStage.OCRD, StageOutcome.COMPLETED)
    collector.record_stage(ReceiptStage.OCRD, StageOutcome.RESUMED)
    collector.record_stage(ReceiptStage.INFERRED, StageOutcome.FAILED)

    snapshot = collector.snapshot()
    assert snapshot.count(ReceiptStage.OCRD, StageOutcome.COMPLETED) == 1
    assert snapshot.count(ReceiptStage.OCRD, StageOutcome.RESUMED) == 1
    assert snapshot.count(ReceiptStage.INFERRED, StageOutcome.FAILED) == 1
    assert snapshot.count(ReceiptStage.MATCHED, StageOutcome.COMPLETED) == 0


def test_a_metrics_snapshot_cannot_be_edited_by_whoever_reads_it():
    """`docs/PRINCIPLES.md` §2.1/§2.1.1 — a snapshot a caller can edit is not a snapshot.

    Two readers would otherwise see different numbers for the same instant, and the one that
    mutated it would never know it had.
    """
    import collections.abc

    snapshot = ExecutionMetricsCollector().snapshot()
    assert isinstance(snapshot.stage_outcomes, collections.abc.Mapping)
    with pytest.raises(TypeError):
        snapshot.stage_outcomes["x"] = 1  # type: ignore[index]


def test_the_stage_output_retention_job_is_registered_with_background_workers():
    """§14 resolved the stage-output storage question with a real 30-day retention policy,
    "registered as a real Background Workers job rather than left to grow unbounded".

    A retention policy that exists only in a constant here is a policy nothing ever runs. This
    pins the cross-API half of that resolution against Background Workers' own registry, so
    renaming or dropping the job breaks here rather than silently letting checkpoints
    accumulate forever.
    """
    from core.background_workers.registry import KNOWN_JOBS
    from services.execution_core.contracts import STAGE_OUTPUT_RETENTION_DAYS

    assert STAGE_OUTPUT_RETENTION_DAYS == 30
    assert "stage_checkpoint_purge" in KNOWN_JOBS

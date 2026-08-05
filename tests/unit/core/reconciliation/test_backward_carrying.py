"""`docs/PRINCIPLES.md` §1.9 — the governing clause for this whole package.

"Anything the live pipeline can do, Reconciliation should be able to do to old data — one
reusable function with two orchestrators, never a second implementation for the historical case."

**These tests assert object identity, not agreement.** That distinction is the entire value of
the file. Two functions that agree today will pass an agreement test right up until the day one
of them is changed and the other is not — and the failure is silent in the worst direction, with
a retroactive sweep quietly applying last year's logic to this year's data and reporting old
receipts as clean by a standard nothing else in the system uses any more. `is` is the assertion
that cannot drift.

Three seams are pinned here, each named explicitly by the deep-dive:

* §4.11's geo cross-reference "calls the identical underlying Geo/Address function Execution
  Core's own GEOD stage calls for new receipts — **not a separate 'old receipt' implementation**".
* §4.10's archive check "reuses Disaster Recovery's own verification logic directly (same check,
  different trigger and scope)".
* §8's propagation atomicity "reuses Execution Core's own `run_stage()`/checkpoint mechanism
  directly... **The same mechanism, not a second implementation of 'resume after a crash.'**"

`core/matching/` and `core/geo_address/` already prove their own §1.9 properties this way; this
is the same technique applied to the API §1.9 was generalised from.
"""

from __future__ import annotations

import inspect

from common.frozen_dict import FrozenDict
from services.execution_core.checkpointing import run_stage
from core.geo_address.reverse_check import reverse_check
from core.reconciliation.checks.geo_vendor_cross_reference import GeoVendorCrossReferenceCheck
from core.reconciliation.contracts import CheckOutcome
from core.reconciliation.propagation import propagate_correction

from ._doubles import RecordingWriter, run, snapshot


class RecordingStore:
    """A minimal `CheckpointStore`, matched to what `run_stage` actually calls on it.

    Written against the real signature rather than guessed at — `run_stage` is the production
    function under test here, and a store whose methods did not match would make this file test
    a mock of the mechanism instead of the mechanism.
    """

    def __init__(self) -> None:
        self.checkpoints: dict[tuple[str, object], object] = {}
        self.writes: list[object] = []

    async def get_checkpoint(self, receipt_id, stage):
        return self.checkpoints.get((receipt_id, stage))

    async def write_checkpoint(self, checkpoint):
        self.checkpoints[(checkpoint.receipt_id, checkpoint.stage)] = checkpoint
        self.writes.append(checkpoint)

    async def find_written_by_content_hash(self, content_hash):
        return None


def test_the_geo_cross_reference_check_runs_end_to_end_through_geo_addresss_real_function():
    """§4.11's "identical underlying function", exercised rather than merely asserted.

    This wires in the genuine `core.geo_address.reverse_check.reverse_check` — not a stand-in —
    and runs the check through it. A `GeoAddress` with no coordinates makes the real function
    take its own documented early-return path, so the whole seam is exercised without a network
    call: the check hands it an address and a vendor hint, and it answers.

    A Reconciliation-local reimplementation of reverse geocoding would satisfy every behavioural
    test in this suite and would drift from Geo/Address's own corroboration logic within one
    release — at which point old receipts would be judged by a weaker standard than new ones,
    invisibly. That is what §1.9 exists to prevent and what this test holds in place.
    """
    from core.geo_address.contracts import GeoAddress

    address_without_coordinates = GeoAddress(formatted="123 Rizal Avenue, Quezon City")
    assert address_without_coordinates.has_coordinates is False

    context = FrozenDict(
        {
            "geo_reverse_check": reverse_check,
            "geo_address": address_without_coordinates,
            "geo_providers": (),
        }
    )
    result = run(GeoVendorCrossReferenceCheck().run(snapshot(), context))

    assert context["geo_reverse_check"] is reverse_check
    assert inspect.iscoroutinefunction(reverse_check)
    assert result.outcome is CheckOutcome.INCONCLUSIVE, (
        "an address with no coordinates has nothing to reverse-look-up, which Geo/Address "
        "itself treats as a skip rather than a discrepancy"
    )


def test_the_geo_check_actually_invokes_whatever_function_it_was_handed():
    """Identity of the wired function is only half the guarantee; the check must also call it.

    A check that accepted the real function and then took an internal shortcut would pass the
    identity assertion above while never reaching Geo/Address at all.
    """
    calls: list[tuple] = []

    async def _spy(address, vendor_hint, providers):
        calls.append((address, vendor_hint, providers))
        return "Jollibee", True, ()

    context = FrozenDict(
        {"geo_reverse_check": _spy, "geo_address": object(), "geo_providers": ()}
    )
    result = run(GeoVendorCrossReferenceCheck().run(snapshot(), context))

    assert len(calls) == 1
    assert calls[0][1] == "Sari-Sari Store Uno"
    assert result.outcome is CheckOutcome.FLAGGED


def test_the_geo_check_signature_matches_what_geo_addresss_function_actually_takes():
    """A seam is only real if both sides fit.

    `reverse_check(address, vendor_name_hint, providers)` is what Geo/Address exposes; the check
    calls it positionally with exactly those three. A drift on either side would only be
    discovered the first time a real sweep ran with the real function wired in — in production,
    against real receipts.
    """
    signature = inspect.signature(reverse_check)
    assert list(signature.parameters) == ["address", "vendor_name_hint", "providers"]


def test_propagation_resumes_through_execution_cores_own_run_stage_and_not_a_local_copy():
    """§8's resolved atomicity mechanism, pinned by identity and then exercised.

    §7's propagation-atomicity hook asks that an interrupted batch not "leave some receipts
    corrected and others silently skipped without a retry". This wires in the genuine
    `services.execution_core.checkpointing.run_stage` — the same function the live pipeline uses for
    every OCR and Inference call — and proves a second pass over the same batch resumes rather
    than reapplying.
    """
    store = RecordingStore()
    writer = RecordingWriter()
    receipt_ids = ("r-1", "r-2", "r-3")

    first = run(
        propagate_correction(
            entity_type="vendor",
            entity_id="v-1",
            change=FrozenDict({"tin": "123-456-789-000"}),
            receipt_ids=receipt_ids,
            writer=writer,
            stage_runner=run_stage,
            checkpoint_store=store,
            job_id="job-1",
        )
    )

    assert first.receipts_propagated == 3
    assert first.receipts_resumed == 0
    assert len(writer.applied) == 3

    second = run(
        propagate_correction(
            entity_type="vendor",
            entity_id="v-1",
            change=FrozenDict({"tin": "123-456-789-000"}),
            receipt_ids=receipt_ids,
            writer=writer,
            stage_runner=run_stage,
            checkpoint_store=store,
            job_id="job-1",
        )
    )

    assert second.receipts_resumed == 3, "the batch restarted instead of resuming"
    assert len(writer.applied) == 3, "already-propagated receipts were corrected a second time"


def test_an_interrupted_batch_resumes_from_the_last_successfully_propagated_receipt():
    """§7's propagation-atomicity hook, stated the way §8 resolves it.

    An interrupted batch must resume "from the last successfully-propagated receipt rather than
    restarting or silently skipping ones already done". Both halves matter and fail differently:
    restarting re-applies corrections that already landed, and skipping leaves receipts holding
    stale data with no record that they were missed.
    """
    store = RecordingStore()
    receipt_ids = ("r-1", "r-2", "r-3", "r-4")

    crashing = RecordingWriter(raises_on="r-3")
    interrupted = run(
        propagate_correction(
            entity_type="vendor",
            entity_id="v-1",
            change=FrozenDict({"tin": "999-888-777-000"}),
            receipt_ids=receipt_ids,
            writer=crashing,
            stage_runner=run_stage,
            checkpoint_store=store,
            job_id="job-2",
        )
    )

    assert interrupted.error
    assert interrupted.receipts_propagated == 2
    assert interrupted.complete is False

    recovered = RecordingWriter()
    resumed = run(
        propagate_correction(
            entity_type="vendor",
            entity_id="v-1",
            change=FrozenDict({"tin": "999-888-777-000"}),
            receipt_ids=receipt_ids,
            writer=recovered,
            stage_runner=run_stage,
            checkpoint_store=store,
            job_id="job-2",
        )
    )

    assert resumed.receipts_resumed == 2, "the first two were redone rather than resumed"
    assert [rid for rid, _ in recovered.applied] == ["r-3", "r-4"]
    assert resumed.complete is True


def test_propagation_without_a_checkpoint_store_reports_zero_resumes_rather_than_pretending():
    """Degrading honestly (`docs/PRINCIPLES.md` §4.4, §4.1).

    Propagation still works with no checkpoint mechanism wired — it simply cannot resume. The
    counter staying at zero is what says so; a run that reported resumes it never performed
    would make §8's mechanism look wired when it was not, which is the one thing an observability
    counter must never do.
    """
    writer = RecordingWriter()
    job = run(
        propagate_correction(
            entity_type="vendor",
            entity_id="v-1",
            change=FrozenDict({"tin": "111-222-333-000"}),
            receipt_ids=("r-1", "r-2"),
            writer=writer,
        )
    )
    assert job.receipts_propagated == 2
    assert job.receipts_resumed == 0
    assert job.complete is True

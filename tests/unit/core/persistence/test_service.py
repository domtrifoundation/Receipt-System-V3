"""The service layer: errors are data at this boundary, and nothing raises out of it."""

from __future__ import annotations

from core.persistence import errors
from core.persistence.metrics import METRIC_DESCRIPTIONS, Metrics
from core.persistence.service import PersistenceService

from .conftest import make_receipt, run


def _service(db, tmp_path):
    return PersistenceService("user-1", db=db, blob_root=tmp_path / "blobs")


def test_a_missing_receipt_is_an_error_code_not_a_raise(db, tmp_path):
    result = run(_service(db, tmp_path).get_receipt("nope"))
    assert not result.ok
    assert result.error_code == errors.RECEIPT_NOT_FOUND
    assert result.receipt is None


def test_a_write_without_an_actor_is_refused(db, tmp_path):
    """An unattributed write has no audit value, so `actor` is required rather than
    defaulted to something anonymous."""
    result = run(_service(db, tmp_path).save_receipt(make_receipt(), actor=""))
    assert not result.ok
    assert result.error_code == errors.INVALID_REQUEST


def test_a_successful_write_returns_its_historian_event_id(db, tmp_path):
    """The caller-visible evidence that the row and its event committed together."""
    result = run(_service(db, tmp_path).save_receipt(make_receipt(), actor="worker"))
    assert result.ok
    assert result.historian_event_id


def test_blob_round_trip_through_the_service(db, tmp_path):
    service = _service(db, tmp_path)
    written = run(service.put_blob(b"some bytes"))
    assert written.ok
    read = run(service.get_blob(written.blob_ref.logical_id, verify=True))
    assert read.ok and read.data == b"some bytes"


def test_metrics_are_counted_and_snapshot_is_immutable(db, tmp_path):
    service = _service(db, tmp_path)
    run(service.save_receipt(make_receipt(), actor="worker"))
    run(service.put_blob(b"a"))
    run(service.put_blob(b"a"))

    snapshot = service.metrics.snapshot()
    assert snapshot["canonical_writes"] == 1
    assert snapshot["historian_data_events"] == 1
    assert snapshot["blob_writes"] == 1
    assert snapshot["blob_dedup_hits"] == 1
    try:
        snapshot["canonical_writes"] = 999  # type: ignore[index]
    except Exception:
        pass
    else:  # pragma: no cover - only reached if the snapshot is mutable
        raise AssertionError("metrics snapshot must not be mutable")


def test_every_declared_metric_exists_on_the_counter():
    metrics = Metrics()
    assert set(metrics.snapshot()) == set(METRIC_DESCRIPTIONS)


def test_archive_sync_is_absent_rather_than_broken_when_unconfigured(db, tmp_path):
    from core.persistence.archive_sync.contracts import SyncTarget

    job = run(_service(db, tmp_path).sync_archives(SyncTarget("google_drive", "a", "user-1")))
    assert not job.ok
    assert job.error_detail


def test_a_reimport_that_blows_up_returns_a_code_and_does_not_raise(tmp_path, db):
    """Errors are data at this boundary (`docs/PRINCIPLES.md` §4.1).

    A hand-edited workbook is the least trustworthy input this API takes and `submit`
    reaches the canonical write path, so an unexpected failure has to become an error code
    rather than an exception on the wire.
    """
    from core.persistence.reimport.contracts import ReimportRequest

    class _Exploding:
        async def submit(self, request):
            raise RuntimeError("boom")

    service = PersistenceService("user-1", db=db, blob_root=tmp_path / "blobs")
    result = run(
        service.submit_reimport(
            ReimportRequest("user-1", "x.xlsx", "user-1", content_scan_passed=True),
            service=_Exploding(),
        )
    )
    assert not result.ok
    assert result.error_code
    assert "boom" in result.error_detail

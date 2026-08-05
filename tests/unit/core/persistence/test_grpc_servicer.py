"""`PersistenceGrpcServicer` — the real gRPC adapter over `PersistenceService`. This was
a real, complete, high-impact gap: `service.py`'s own module docstring described "the
generated servicer is a one-line-per-RPC adapter over this class," but no `.proto`
compilation, no generated stubs, and no adapter existed anywhere in this package until
this session (`grpc_servicer.py`'s own module docstring)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.persistence.blob_store.backup.base import BackupRegistry, InMemoryTarget  # noqa: E402
from core.persistence.db.connection import default_db_path  # noqa: E402
from core.persistence.generated import persistence_pb2 as pb  # noqa: E402
from core.persistence.grpc_servicer import PersistenceGrpcServicer  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _receipt_message(receipt_id="r1", user_id="u1", logical_id="", **overrides):
    fields = dict(
        receipt_id=receipt_id, user_id=user_id, blob=pb.BlobRefMessage(logical_id=logical_id),
        vendor_name="Acme Corp", currency="PHP", total_amount="100.00",
        created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
    )
    fields.update(overrides)
    return pb.ReceiptMessage(**fields)


def test_put_blob_and_get_blob_round_trip(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)

    put = run(servicer.PutBlob(pb.PutBlobRequest(user_id="u1", original_bytes=b"real bytes", codec="original")))
    assert put.error_code == ""
    assert put.blob.logical_id

    got = run(servicer.GetBlob(pb.GetBlobRequest(user_id="u1", logical_id=put.blob.logical_id)))
    assert got.error_code == ""
    assert got.data == b"real bytes"


def test_save_receipt_then_get_receipt_round_trip(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)
    put = run(servicer.PutBlob(pb.PutBlobRequest(user_id="u1", original_bytes=b"receipt image", codec="original")))
    msg = _receipt_message(logical_id=put.blob.logical_id)

    saved = run(servicer.SaveReceipt(pb.SaveReceiptRequest(receipt=msg, actor="human:u1")))
    assert saved.error_code == ""
    assert saved.receipt_id == "r1"
    assert saved.historian_event_id != ""

    got = run(servicer.GetReceipt(pb.GetReceiptRequest(user_id="u1", receipt_id="r1")))
    assert got.error_code == ""
    assert got.receipt.vendor_name == "Acme Corp"
    assert got.receipt.total_amount == "100.00"


def test_get_receipt_reports_receipt_not_found_for_an_unknown_id(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)

    response = run(servicer.GetReceipt(pb.GetReceiptRequest(user_id="u1", receipt_id="nope")))

    assert response.error_code == "receipt_not_found"


def test_save_receipt_requires_an_actor(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)
    msg = _receipt_message()

    response = run(servicer.SaveReceipt(pb.SaveReceiptRequest(receipt=msg, actor="")))

    assert response.error_code == "invalid_request"


def test_list_receipts_returns_every_saved_receipt_for_the_user(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)
    run(servicer.SaveReceipt(pb.SaveReceiptRequest(receipt=_receipt_message("r1"), actor="human:u1")))
    run(servicer.SaveReceipt(pb.SaveReceiptRequest(receipt=_receipt_message("r2"), actor="human:u1")))

    response = run(servicer.ListReceipts(pb.ListReceiptsRequest(user_id="u1")))

    assert {r.receipt_id for r in response.receipts} == {"r1", "r2"}


def test_receipts_are_isolated_per_user(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)
    run(servicer.SaveReceipt(pb.SaveReceiptRequest(receipt=_receipt_message("r1", user_id="u1"), actor="human:u1")))
    run(servicer.SaveReceipt(pb.SaveReceiptRequest(receipt=_receipt_message("r2", user_id="u2"), actor="human:u2")))

    u1_list = run(servicer.ListReceipts(pb.ListReceiptsRequest(user_id="u1")))
    u2_list = run(servicer.ListReceipts(pb.ListReceiptsRequest(user_id="u2")))

    assert {r.receipt_id for r in u1_list.receipts} == {"r1"}
    assert {r.receipt_id for r in u2_list.receipts} == {"r2"}


def test_get_receipt_history_returns_the_real_historian_event(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)
    run(servicer.SaveReceipt(pb.SaveReceiptRequest(receipt=_receipt_message("r1"), actor="human:u1")))

    history = run(servicer.GetReceiptHistory(pb.ReceiptHistoryRequest(user_id="u1", receipt_id="r1")))

    assert len(history.entries) == 1
    assert history.entries[0].track == "data_change"
    assert history.entries[0].actor == "human:u1"


def test_list_export_providers_returns_a_real_tuple_not_an_error(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)

    response = run(servicer.ListExportProviders(pb.ListExportProvidersRequest()))

    assert list(response.provider_names) == []


def test_submit_reimport_reports_a_real_error_for_a_missing_file(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)

    response = run(servicer.SubmitReimport(pb.ReimportUpload(
        user_id="u1", file_path=str(tmp_path / "does-not-exist.xlsx"),
        actor_user_id="u1", content_scan_passed=True,
    )))

    assert response.error_code != ""


def test_enable_sync_mirrors_a_real_file_to_a_local_folder(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)
    put = run(servicer.PutBlob(pb.PutBlobRequest(user_id="u1", original_bytes=b"archive me", codec="original")))
    run(servicer.SaveReceipt(pb.SaveReceiptRequest(receipt=_receipt_message("r1", logical_id=put.blob.logical_id), actor="human:u1")))
    mirror_dir = tmp_path / "mirror"
    mirror_dir.mkdir()

    enabled = run(servicer.EnableSync(pb.EnableSyncRequest(
        user_id="u1", provider_name="local_folder", target_path=str(mirror_dir), enabled=True,
    )))

    assert enabled.error_code == ""
    assert enabled.state == "active"
    mirrored_files = [f for f in mirror_dir.rglob("*") if f.is_file()]
    assert len(mirrored_files) == 1


def test_get_sync_status_reflects_disabled_after_enable_sync_false(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)
    mirror_dir = tmp_path / "mirror"
    mirror_dir.mkdir()
    run(servicer.EnableSync(pb.EnableSyncRequest(
        user_id="u1", provider_name="local_folder", target_path=str(mirror_dir), enabled=True,
    )))

    run(servicer.EnableSync(pb.EnableSyncRequest(
        user_id="u1", provider_name="local_folder", target_path=str(mirror_dir), enabled=False,
    )))
    status = run(servicer.GetSyncStatus(pb.SyncStatusRequest(user_id="u1", provider_name="local_folder")))

    assert status.state == "disabled"


def test_start_restore_then_get_restore_status_and_verify_integrity(tmp_path: Path):
    source_top = tmp_path / "source"
    target_dir = tmp_path / "restored" / "u1"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir(parents=True)

    registry = BackupRegistry([InMemoryTarget("memtarget")])
    servicer = PersistenceGrpcServicer(top_level=source_top, backups=registry)
    run(servicer.PutBlob(pb.PutBlobRequest(user_id="u1", original_bytes=b"restore me", codec="original")))

    src_db_path = default_db_path(source_top, "u1")
    snap_path = snapshot_dir / "snap.sqlite"
    src_conn = sqlite3.connect(str(src_db_path))
    dst_conn = sqlite3.connect(str(snap_path))
    with dst_conn:
        src_conn.backup(dst_conn)
    src_conn.close()
    dst_conn.close()

    restored = run(servicer.StartRestore(pb.RestoreRequest(
        snapshot_id="snap-1", target_dir=str(target_dir), snapshot_source=str(snap_path),
        scope="single_user", user_id="u1",
    )))
    assert restored.stage == "complete"
    assert restored.error_code == ""

    status = run(servicer.GetRestoreStatus(pb.RestoreStatusRequest(job_id=restored.job_id)))
    assert status.job_id == restored.job_id
    assert status.stage == "complete"

    verify = run(servicer.VerifyIntegrity(pb.VerifyRequest(target_dir=str(target_dir), require_blobs_present=True)))
    assert verify.clean is True
    assert verify.total_refs_checked == 1


def test_get_restore_status_reports_an_error_for_an_unknown_job_id(tmp_path: Path):
    servicer = PersistenceGrpcServicer(top_level=tmp_path)

    response = run(servicer.GetRestoreStatus(pb.RestoreStatusRequest(job_id="does-not-exist")))

    assert response.error_code != ""

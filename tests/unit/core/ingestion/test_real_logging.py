"""The real proof this fix exists for: a failure inside `IngestionServicer`'s own
best-effort paths must actually be queryable afterward, not vanish. Confirmed here
end to end — a real `LogWriter` writes to a real file, and a real `LogReader`/`query.py`
reads it back with its full traceback intact, the same path Logs API's own `Query` RPC
uses.
"""

from __future__ import annotations

import asyncio

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.ingestion.contracts import IngestionError, IngestionErrorCode, NormalizationResult  # noqa: E402
from core.ingestion.service import IngestionServicer  # noqa: E402
from core.logs.contracts import LogQuery  # noqa: E402
from core.logs.index import LogIndex  # noqa: E402
from core.logs.query import LogReader  # noqa: E402
from core.logs.sinks import JsonlFileSink, SinkRegistry  # noqa: E402
from core.logs.writer import LogWriter  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _AllowAllChecker:
    """A permissive `AccessChecker` — these tests are proving an entry exists and is
    shaped correctly, not re-testing Logs' own already-covered permission gate."""

    def allow_cross_user(self, requesting_user_id, subject_user_id) -> bool:
        return True


def _real_writer(tmp_path):
    index = LogIndex(tmp_path / "index.sqlite", root=tmp_path)
    registry = SinkRegistry()
    registry.register(JsonlFileSink(tmp_path))
    return LogWriter(tmp_path, registry=registry, index=index), index


def test_a_failed_submit_for_processing_is_actually_queryable_afterward(blob_store, tmp_path):
    writer, index = _real_writer(tmp_path)
    servicer = IngestionServicer(blob_store, execution_core_address="127.0.0.1:1", log_writer=writer)

    result = NormalizationResult(images=(), archival_blob_ref=None)
    # A genuinely reachable-but-refusing address (nothing listens on port 1) forces a real
    # gRPC failure inside _submit_for_processing's own try block.
    run(servicer._submit_for_processing("run-1", "user-1", result))
    writer.close()

    reader = LogReader(tmp_path, index=index, checker=_AllowAllChecker())
    entries = reader.read(LogQuery(service="ingestion", requesting_user_id="owner")).entries

    assert len(entries) == 1
    assert entries[0].level.value == "error"
    assert "run-1" in entries[0].message
    assert entries[0].traceback  # the real, full traceback -- never str(exc)


def test_a_failed_drive_file_in_a_batch_is_logged_and_the_batch_continues(blob_store, tmp_path):
    from core.ingestion.contracts import SourceKind
    from core.ingestion.webhook_manager.contracts import ChangeEvent, WebhookProvider

    writer, index = _real_writer(tmp_path)
    servicer = IngestionServicer(blob_store, log_writer=writer)

    class _BrokenDriveSource:
        async def download(self, **kwargs):
            raise RuntimeError("simulated Drive download failure")

    servicer._registry._sources[SourceKind.GOOGLE_DRIVE] = _BrokenDriveSource()

    events = (ChangeEvent(provider=WebhookProvider.GOOGLE_DRIVE, file_id="file1", change_type="added"),)
    run(servicer._process_drive_events(events))
    writer.close()

    reader = LogReader(tmp_path, index=index, checker=_AllowAllChecker())
    entries = reader.read(LogQuery(service="ingestion", requesting_user_id="owner")).entries

    assert len(entries) == 1
    assert "file1" in entries[0].message
    assert "simulated Drive download failure" in entries[0].traceback

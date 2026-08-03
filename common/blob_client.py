"""A real gRPC client implementing the `BlobStoreGateway` Protocol shape every consuming
API (OCR, Preprocessing, Ingestion) independently declares (`docs/PRINCIPLES.md` §1.3 —
each defines its own narrow `Protocol`, this is the one concrete implementation any of
them can be constructed with, satisfied structurally since Python `Protocol`s don't
require inheritance).

**The real, previously-missing piece those three APIs' own `service.py` docstrings
already named explicitly** — OCR's own `__main__` said outright: "No default blob_store
is wired up yet — this module needs a real Persistence blob-store client to run
standalone." This is that client, calling Persistence's real `PutBlob`/`GetBlob` RPCs
(`core/persistence/grpc_servicer.py`), never a fake/in-memory stand-in.

`user_id` defaults to `"local"` — every user-scoped RPC in this project's single-tenant
mode already resolves through Auth's own implicit-owner path to one effective user; this
client's own default matches that same single-user assumption for a local/dev launch,
not a fabricated identity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GrpcBlobRef:
    logical_id: str


class GrpcBlobStoreClient:
    """Structurally satisfies `read_blob(ref) -> bytes` / `write_blob(data) -> BlobRef`
    for OCR/Preprocessing/Ingestion's own `BlobStoreGateway` Protocols."""

    def __init__(self, address: str, *, user_id: str = "local") -> None:
        self._address = address
        self._user_id = user_id
        self._channel = None
        self._stub = None

    def _ensure_stub(self):
        if self._stub is None:
            import grpc

            from core.persistence.generated import persistence_pb2_grpc

            self._channel = grpc.aio.insecure_channel(self._address)
            self._stub = persistence_pb2_grpc.PersistenceServiceStub(self._channel)
        return self._stub

    async def write_blob(self, data: bytes) -> GrpcBlobRef:
        from core.persistence.generated import persistence_pb2

        stub = self._ensure_stub()
        response = await stub.PutBlob(
            persistence_pb2.PutBlobRequest(original_bytes=data, user_id=self._user_id)
        )
        return GrpcBlobRef(logical_id=response.blob.logical_id)

    async def read_blob(self, ref: GrpcBlobRef) -> bytes:
        from core.persistence.generated import persistence_pb2

        stub = self._ensure_stub()
        response = await stub.GetBlob(
            persistence_pb2.GetBlobRequest(logical_id=ref.logical_id, user_id=self._user_id)
        )
        if response.error_code:
            raise RuntimeError(f"{response.error_code}: {response.error_detail}")
        return response.data

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()


__all__ = ["GrpcBlobRef", "GrpcBlobStoreClient"]

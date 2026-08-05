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

import json
from dataclasses import dataclass
from pathlib import Path

#: Matches `supervisor/__main__.py`'s own `SERVICE_ADDRESSES_RELPATH` — duplicated as a
#: constant rather than imported, since this module must stay importable from inside a
#: service's own venv, which has no `supervisor` package on it (`docs/PRINCIPLES.md`
#: §1.3's Protocol-seam discipline applied to a file path, not just a type).
SERVICE_ADDRESSES_RELPATH = Path("supervisor") / "service_addresses.json"


def resolve_service_address(install_root: Path, service_name: str, fallback: str) -> str:
    """Reads Supervisor's own real, dynamically-bound address registry
    (`supervisor/__main__.py`'s `_write_service_addresses`) — the actual answer to "how
    does one service find another when ports are ephemeral, not fixed constants."
    Degrades to `fallback` (never raises) if the registry file doesn't exist yet, is
    unreadable, or doesn't have this service listed — the same graceful-degrade posture
    every other optional collaborator in this project already follows
    (`docs/PRINCIPLES.md` §4.4), since a launch order where the dependency hasn't
    published its address yet is a real, expected transient state, not an error.
    """
    target = install_root / SERVICE_ADDRESSES_RELPATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        resolved = data.get(service_name)
        return resolved if isinstance(resolved, str) and resolved else fallback
    except (OSError, json.JSONDecodeError):
        return fallback


@dataclass(frozen=True)
class GrpcBlobRef:
    logical_id: str


class GrpcBlobStoreClient:
    """Structurally satisfies `read_blob(ref) -> bytes` / `write_blob(data) -> BlobRef`
    for OCR/Preprocessing/Ingestion's own `BlobStoreGateway` Protocols.

    `install_root`, when given, is what makes this a real dynamic-port lookup instead of
    a fixed address — resolved lazily on first actual RPC (`_ensure_stub`), never at
    construction time, since the registry file may not exist yet the moment this client
    object is built (early in a sibling service's own startup, before Persistence itself
    has necessarily reported its own address).
    """

    def __init__(self, address: str, *, user_id: str = "local", install_root: Path | None = None) -> None:
        self._fallback_address = address
        self._install_root = install_root
        self._user_id = user_id
        self._channel = None
        self._stub = None

    def _resolve_address(self) -> str:
        if self._install_root is None:
            return self._fallback_address
        return resolve_service_address(self._install_root, "persistence", self._fallback_address)

    def _ensure_stub(self):
        if self._stub is None:
            import grpc

            from common.grpc_limits import GRPC_MESSAGE_SIZE_OPTIONS
            from core.persistence.generated import persistence_pb2_grpc

            self._channel = grpc.aio.insecure_channel(
                self._resolve_address(), options=GRPC_MESSAGE_SIZE_OPTIONS
            )
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

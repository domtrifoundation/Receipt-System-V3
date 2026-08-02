"""Persistence API — all disk access in this system, and nothing else's.

Import from `core.persistence.contracts`; that module is the only one other packages have
any reason to import (`docs/PRINCIPLES.md` §1.1). `service.py` is the surface every gRPC RPC
maps onto.

If you are reaching for `open()` outside this package, that is the bug.
"""

from .contracts import (
    BlobLocation,
    BlobReadResult,
    BlobRef,
    BlobWriteResult,
    Receipt,
    ReceiptReadResult,
    ReferenceIdentifier,
    StorageCodec,
    WriteResult,
)
from .service import PersistenceService

__all__ = [
    "BlobLocation",
    "BlobReadResult",
    "BlobRef",
    "BlobWriteResult",
    "PersistenceService",
    "Receipt",
    "ReceiptReadResult",
    "ReferenceIdentifier",
    "StorageCodec",
    "WriteResult",
]

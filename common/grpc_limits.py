"""Shared gRPC message-size ceiling.

Real-world scanned/photographed receipts routinely exceed gRPC's 4 MiB default
(`RealReceiptsSamples.zip`'s own samples include one at 9.2 MB) -- live-found via a
full-fleet concurrent-submission test that failed every such upload with
`RESOURCE_EXHAUSTED` before this existed. Every `grpc.aio.server()`/`grpc.server()` and
every channel that may carry a full file's raw bytes (never a summary/reference) should
pass `GRPC_MESSAGE_SIZE_OPTIONS` so the ceiling is one number, not a value copied at each
of this repo's ~34 call sites and inevitably drifting.

Scope, stated honestly: only the direct-upload path (Ingestion's server, Content
Security's server, and the client channel between them) uses this today. The identical
gap -- gRPC's 4 MiB default left unset -- exists at every other `grpc.aio.server()`/
`grpc.server()` call site in the repo; wiring this in everywhere is the same mechanical
fix, real, separate, larger follow-up work, not done here.
"""

from __future__ import annotations

#: 32 MiB -- comfortably above any real receipt sample seen so far, small enough that a
#: hostile oversized payload still fails fast rather than being accepted unbounded.
MAX_MESSAGE_BYTES = 32 * 1024 * 1024

GRPC_MESSAGE_SIZE_OPTIONS = [
    ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
    ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
]

__all__ = ["MAX_MESSAGE_BYTES", "GRPC_MESSAGE_SIZE_OPTIONS"]

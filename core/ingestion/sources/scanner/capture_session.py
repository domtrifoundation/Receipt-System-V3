"""A server-side session for an in-progress multi-frame scan (deep-dive §4.3.2). The
client's live corner-detection/perspective-correction runs entirely client-side
(`opencv.js`, deep-dive §4.3.1) — this module only tracks the raw frames a panorama
capture submits one at a time, and finalizes them into a single `SourceFile` (stitching
via `stitcher.py` when there's more than one frame).

A plain in-memory session store, keyed by `session_id` — a scan session is short-lived
(one user, one capture flow, seconds to a couple of minutes) and does not need
Persistence-backed durability the way a `SourceFile` itself does once finalized.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from ...contracts import BlobStoreGateway, SourceFile, SourceKind
from ...errors import StitchFailed
from .stitcher import stitch_panorama

__all__ = ["CaptureSession", "CaptureSessionStore"]

#: A session with no `FinalizeScanSession` call within this window is treated as
#: abandoned — a client that disconnects mid-capture must not leak memory forever.
SESSION_TTL_SECONDS = 900


@dataclass
class CaptureSession:
    session_id: str
    run_id: str
    user_id: str
    created_at: float = field(default_factory=time.monotonic)
    frames: list[bytes] = field(default_factory=list)

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.monotonic()) - self.created_at > SESSION_TTL_SECONDS


class CaptureSessionStore:
    """A plain mutable dict, not a `FrozenDict` — genuinely mutable runtime state
    (`docs/PRINCIPLES.md` §2.1.1's own carve-out), same category as `core/ocr/
    engine_registry.py`'s own cloud-call-count tracking."""

    def __init__(self) -> None:
        self._sessions: dict[str, CaptureSession] = {}

    def start(self, run_id: str, user_id: str) -> CaptureSession:
        self._purge_expired()
        session = CaptureSession(session_id=str(uuid.uuid4()), run_id=run_id, user_id=user_id)
        self._sessions[session.session_id] = session
        return session

    def _purge_expired(self) -> None:
        expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired:
            del self._sessions[sid]

    def get(self, session_id: str) -> CaptureSession | None:
        return self._sessions.get(session_id)

    def submit_frame(self, session_id: str, frame_bytes: bytes) -> int:
        """Returns the 0-based index of the newly-submitted frame. Raises `KeyError` for
        an unknown/expired session — a caller error, not a data-carried failure."""
        session = self._sessions[session_id]
        session.frames.append(frame_bytes)
        return len(session.frames) - 1

    async def finalize(self, session_id: str, blob_store: BlobStoreGateway) -> SourceFile:
        """Stitches (if >1 frame) or uses the lone frame directly, stages the result as a
        `SourceFile`, and removes the session. Raises `KeyError` for an unknown session,
        `StitchFailed` if stitching genuinely fails."""
        session = self._sessions.pop(session_id)
        if not session.frames:
            raise StitchFailed(-1, "no frames were submitted to this scan session")

        if len(session.frames) == 1:
            final_bytes = session.frames[0]
        else:
            import cv2
            import numpy as np

            decoded = []
            for frame_bytes in session.frames:
                array = cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                if array is None:
                    raise StitchFailed(-1, "a submitted frame failed to decode")
                decoded.append(array)
            stitched = await stitch_panorama(tuple(decoded))
            ok, buf = cv2.imencode(".png", stitched)
            if not ok:
                raise StitchFailed(-1, "failed to encode the stitched panorama")
            final_bytes = buf.tobytes()

        raw_ref = await blob_store.write_blob(final_bytes)
        return SourceFile(
            run_id=session.run_id, user_id=session.user_id, source=SourceKind.SCANNER,
            raw_blob_ref=raw_ref, original_filename=f"scan-{session.session_id}.png",
            declared_mime_type="image/png",
        )

"""Archival re-encode (deep-dive §3) — one codec for the whole install, owner-selected,
never a per-user/tier lever. Both AVIF and WebP go through the same Pillow call (`Image.
save(..., format=...)`) — Pillow's own native AVIF support (11.3+) means switching the
owner's choice is a config value, not two maintained code paths.

**The content-address hash is computed over the original uploaded bytes, before
re-encoding** (deep-dive §3) — this module never computes or touches that hash itself;
it only produces the re-encoded bytes. Persistence's own `BlobLocation` mapping is what
resolves a stable `logical_id` (keyed on the original bytes' hash) to whichever
`physical_hash` the currently-configured codec happens to produce — this module has no
opinion about that split, it just applies whichever codec the caller configured.

Hardware-accelerated encode deliberately not used (deep-dive §3's own reasoning: AV1
hardware encode needs newer hardware than this project can assume, and no vendor ships a
WebP hardware encoder at all) — plain Pillow/libavif software encode, fast enough at this
workload's real per-run image count.
"""

from __future__ import annotations

import asyncio
import io

from .errors import CodecEncodeFailed, UnsupportedFormat

__all__ = ["ArchivalCodec", "encode_archival"]

#: The two owner-selectable choices (deep-dive §3, §9's config sketch:
#: `archival_codec: avif | webp`). Not an enum reused from elsewhere — this is this
#: module's own narrow vocabulary, matching Pillow's own `format=` argument spelling.
ArchivalCodec = str
_SUPPORTED_CODECS = frozenset({"avif", "webp"})


def _encode_sync(data: bytes, codec: str, quality: int) -> bytes:
    import pillow_heif
    from PIL import Image

    # Idempotent — registers HEIC/HEIF support with Pillow's own plugin system. Called
    # here directly (not relied upon as a side effect of importing `core.preprocessing.
    # raster` elsewhere) so this module works correctly on its own, independent of import
    # order in whatever process assembles the real pipeline.
    pillow_heif.register_heif_opener()

    if codec not in _SUPPORTED_CODECS:
        raise UnsupportedFormat(f"unsupported archival codec {codec!r}; must be one of {sorted(_SUPPORTED_CODECS)}")

    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB") if image.mode not in ("RGB", "RGBA") else image
            buffer = io.BytesIO()
            image.save(buffer, format=codec.upper(), quality=quality)
            return buffer.getvalue()
    except UnsupportedFormat:
        raise
    except Exception as exc:  # noqa: BLE001 - any encode-path failure is a codec failure
        raise CodecEncodeFailed(f"{type(exc).__name__}: {exc}") from exc


async def encode_archival(data: bytes, *, codec: str = "avif", quality: int = 75) -> bytes:
    """Re-encodes already-decoded image bytes (any Pillow-openable format, including HEIC
    once `pillow_heif.register_heif_opener()` has run — Preprocessing's own `raster.py`
    already does this at import time, and this module is always used alongside it in the
    real pipeline) into the owner's configured archival codec."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _encode_sync, data, codec, quality)

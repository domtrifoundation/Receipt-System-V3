"""Shared dependency-download infrastructure (`v3-deepdive-36-proving-grounds.md` §3) —
"the concrete download machinery Setup API's own initial dependency installation ... relies
on, not duplicated ... one implementation serves both 'install this for the first time'
(Setup) and 'download this candidate to test it' (Proving Grounds) use cases."

**HF token-auth support is real, not a TODO** — §3's own explicit hardening requirement,
directly relevant to Inference API's preset resolution (its deep-dive §4.4: gated Hugging
Face model repos need a bearer token). `download_file()` sends `Authorization: Bearer
<token>` whenever a token is supplied, regardless of host — the caller decides when a
token applies (a candidate naming a non-HF URL simply has no `hf_token` set), this module
does not special-case Hugging Face's own domain.

**Streamed, not buffered whole** — a candidate download can be a multi-gigabyte model or
wheel; `httpx`'s own streaming response is used so this never holds a full artifact in
memory at once.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from .contracts import DownloadResult

__all__ = ["DEFAULT_CHUNK_SIZE", "download_file"]

#: 1 MiB — large enough that per-chunk overhead is negligible, small enough that a stalled
#: download's own progress is still observable at a reasonable granularity.
DEFAULT_CHUNK_SIZE = 1024 * 1024


async def download_file(
    url: str,
    destination: Path | str,
    *,
    hf_token: str = "",
    timeout_seconds: float = 300.0,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> DownloadResult:
    """Streams `url` to `destination`, creating parent directories as needed. Never
    raises — a network failure, a non-2xx status, or a filesystem error are all a
    `DownloadResult(ok=False, ...)` (`docs/PRINCIPLES.md` §4.1).
    """
    destination = Path(destination)
    headers = {"Authorization": f"Bearer {hf_token}"} if hf_token else {}

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                with destination.open("wb") as fh:
                    async for chunk in response.aiter_bytes(chunk_size):
                        fh.write(chunk)
                        bytes_written += len(chunk)
    except httpx.HTTPError as exc:
        return DownloadResult(ok=False, error_code="DOWNLOAD_FAILED", error_detail=str(exc))
    except OSError as exc:
        return DownloadResult(ok=False, error_code="DOWNLOAD_FAILED", error_detail=str(exc))

    return DownloadResult(ok=True, destination=str(destination), bytes_written=bytes_written)

"""Shared dependency-download infrastructure (`v3-deepdive-36-proving-grounds.md` §3) —
"the concrete download machinery Setup API's own initial dependency installation ... relies
on, not duplicated ... one implementation serves both 'install this for the first time'
(Setup) and 'download this candidate to test it' (Proving Grounds) use cases." Inference
API's own model provisioning (`core/inference/model_provisioning.py`) is a third real
caller of this same module, for the identical reason — one resumable download
implementation, not three.

**HF token-auth support is real, not a TODO** — §3's own explicit hardening requirement,
directly relevant to Inference API's preset resolution (its deep-dive §4.4: gated Hugging
Face model repos need a bearer token). `download_file()` sends `Authorization: Bearer
<token>` whenever a token is supplied, regardless of host — the caller decides when a
token applies (a candidate naming a non-HF URL simply has no `hf_token` set), this module
does not special-case Hugging Face's own domain.

**Streamed, not buffered whole** — a candidate download can be a multi-gigabyte model or
wheel; `httpx`'s own streaming response is used so this never holds a full artifact in
memory at once.

**Resumable, real reason not a nice-to-have**: model files provisioned by Inference API
are multi-gigabyte (`core/inference/CLAUDE.md`'s own live-confirmed download timings), and
a network blip partway through one must not mean starting over from byte 0. `download_file`
checks for an existing partial `destination` and sends `Range: bytes=<size>-`; a server
that honors it (`206 Partial Content`) gets appended to, one that doesn't (`200 OK`, or
`416 Range Not Satisfiable` meaning the local partial is stale/corrupt) gets restarted
clean. Layered with a bounded whole-attempt retry, mirroring
`services/setup/venv_provisioning.py`'s own `_run_with_retries` pattern added for the
identical reason (a transient network blip must not fail the whole operation) — the two
are deliberately the same shape, not independently reinvented.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from .contracts import DownloadResult

__all__ = ["DEFAULT_CHUNK_SIZE", "download_file"]

#: 1 MiB — large enough that per-chunk overhead is negligible, small enough that a stalled
#: download's own progress is still observable at a reasonable granularity.
DEFAULT_CHUNK_SIZE = 1024 * 1024

#: Whole-attempt retry count and delay — same shape and same reasoning as
#: `venv_provisioning.PIP_INSTALL_ATTEMPTS`/`PIP_INSTALL_RETRY_DELAY_SECONDS`: a genuinely
#: broken URL/host fails identically on every attempt, so retrying never masks a real
#: error, only bounds how long a transient one is allowed to cost.
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 3.0

_STATUS_PARTIAL_CONTENT = 206
_STATUS_RANGE_NOT_SATISFIABLE = 416


async def download_file(
    url: str,
    destination: Path | str,
    *,
    hf_token: str = "",
    timeout_seconds: float = 300.0,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    resume: bool = True,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> DownloadResult:
    """Streams `url` to `destination`, creating parent directories as needed. Never
    raises — a network failure, a non-2xx status, or a filesystem error are all a
    `DownloadResult(ok=False, ...)` (`docs/PRINCIPLES.md` §4.1).

    Retries up to `max_attempts` times on failure, resuming from wherever the previous
    attempt left off (`resume=True`, the default) rather than restarting from byte 0 —
    real, live-relevant given Inference API's own multi-gigabyte model files. Pass
    `resume=False` for content where a partial file is never a valid resume point (there
    is none in this repo today, but the caller's choice belongs to the caller, not a
    hardcoded assumption here).
    """
    destination = Path(destination)
    attempt = 1
    result = await _attempt_download(
        url, destination, hf_token=hf_token, timeout_seconds=timeout_seconds,
        chunk_size=chunk_size, resume=resume,
    )
    while not result.ok and attempt < max_attempts:
        await asyncio.sleep(retry_delay_seconds)
        attempt += 1
        result = await _attempt_download(
            url, destination, hf_token=hf_token, timeout_seconds=timeout_seconds,
            chunk_size=chunk_size, resume=resume,
        )
    return result


async def _attempt_download(
    url: str,
    destination: Path,
    *,
    hf_token: str,
    timeout_seconds: float,
    chunk_size: int,
    resume: bool,
) -> DownloadResult:
    existing_bytes = destination.stat().st_size if resume and destination.exists() else 0
    headers = {"Authorization": f"Bearer {hf_token}"} if hf_token else {}
    if existing_bytes > 0:
        headers["Range"] = f"bytes={existing_bytes}-"

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code == _STATUS_RANGE_NOT_SATISFIABLE:
                    # The server considers `existing_bytes` past the real end of the
                    # file -- the local partial is stale or was corrupted mid-write on a
                    # prior crash. The only safe move is to discard it and restart clean,
                    # never trust a partial file's own size as ground truth over the
                    # server's.
                    destination.unlink(missing_ok=True)
                    return await _attempt_download(
                        url, destination, hf_token=hf_token, timeout_seconds=timeout_seconds,
                        chunk_size=chunk_size, resume=False,
                    )

                response.raise_for_status()
                # A server that ignores `Range` entirely answers `200` with the FULL body
                # rather than `206` with the remainder -- appending that to
                # `existing_bytes` would silently duplicate/corrupt the file. Detected
                # per-response (never assumed from the request alone, since some servers
                # do honor Range and some don't), and handled by writing fresh rather
                # than appending.
                resumed = existing_bytes > 0 and response.status_code == _STATUS_PARTIAL_CONTENT
                mode = "ab" if resumed else "wb"
                bytes_written = existing_bytes if resumed else 0
                with destination.open(mode) as fh:
                    async for chunk in response.aiter_bytes(chunk_size):
                        fh.write(chunk)
                        bytes_written += len(chunk)
    except httpx.HTTPError as exc:
        return DownloadResult(ok=False, error_code="DOWNLOAD_FAILED", error_detail=str(exc))
    except OSError as exc:
        return DownloadResult(ok=False, error_code="DOWNLOAD_FAILED", error_detail=str(exc))

    return DownloadResult(
        ok=True, destination=str(destination), bytes_written=bytes_written, resumed=resumed
    )

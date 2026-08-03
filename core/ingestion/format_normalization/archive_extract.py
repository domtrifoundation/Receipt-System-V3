"""Zip archive handling for bulk-upload batches (deep-dive §5) — Python's built-in
`zipfile`, zero extra dependency.

**This module never scans anything itself.** Content Security's own container-level bomb
check (`infolist()` metadata — compression ratio, cumulative uncompressed total, entry
count, nesting depth) runs *before* any extraction happens at all; this module only
enumerates and extracts entries after that container-level check has already cleared them,
and every extracted entry still gets its own individual Content Security pass afterward —
a bomb-free container could still smuggle one bad file among good ones (deep-dive §5's own
two-pass model, owned entirely by Content Security's own deep-dive, not reimplemented
here).
"""

from __future__ import annotations

import asyncio
import zipfile

from .errors import ArchiveExtractFailed

__all__ = ["ArchiveEntry", "extract_entries", "list_entries"]


class ArchiveEntry:
    __slots__ = ("filename", "data")

    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self.data = data


def _list_entries_sync(zip_bytes: bytes) -> list[str]:
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            return [info.filename for info in archive.infolist() if not info.is_dir()]
    except zipfile.BadZipFile as exc:
        raise ArchiveExtractFailed(f"not a valid zip archive: {exc}") from exc


def _extract_entries_sync(zip_bytes: bytes) -> list[ArchiveEntry]:
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            entries = []
            for info in archive.infolist():
                if info.is_dir():
                    continue
                entries.append(ArchiveEntry(info.filename, archive.read(info)))
            return entries
    except zipfile.BadZipFile as exc:
        raise ArchiveExtractFailed(f"not a valid zip archive: {exc}") from exc


async def list_entries(zip_bytes: bytes) -> tuple[str, ...]:
    """Filenames only — this is the cheap enumeration Content Security's own container
    bomb-check reads (`infolist()` metadata) before this module ever reads entry bytes."""
    loop = asyncio.get_running_loop()
    return tuple(await loop.run_in_executor(None, _list_entries_sync, zip_bytes))


async def extract_entries(zip_bytes: bytes) -> tuple[ArchiveEntry, ...]:
    """Every non-directory entry's raw bytes — called only after the container-level bomb
    check has already cleared this archive (the caller's own responsibility, not this
    module's)."""
    loop = asyncio.get_running_loop()
    return tuple(await loop.run_in_executor(None, _extract_entries_sync, zip_bytes))

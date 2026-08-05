"""Container-level (zip) bomb checks (§3) — read `zipfile.infolist()` metadata only, before
any extraction happens at all. A bomb-free container can still hold one bad file: this module
answers "is the container itself safe to extract," never "is every file inside it safe" —
that is the per-member scan pass `pipeline.py` runs second, against members this module has
already cleared for extraction.

**Never call `ZipFile.extractall()` or `.read()` from this module.** `infolist()` reads the
central directory only; it is what makes it possible to reason about a hostile archive's own
claimed size and entry count without decompressing a single byte of attacker-controlled data.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence

from ..contracts import BombCheckResult, RemediationResult
from ..errors import NotAValidContainer

#: Chosen to be generous for real receipt-batch uploads (a few dozen images, rarely more than
#: single-digit MB each) while still catching an archive engineered to blow past any
#: reasonable batch size. `docs/PRINCIPLES.md` §5 marks a scorer default/threshold like this
#: as reasoned-then-measured — provisional until the bench suite has real upload data to tune
#: it against, not asserted as a final number here.
MAX_ENTRY_COUNT = 2_000
MAX_TOTAL_UNCOMPRESSED_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB
MAX_AGGREGATE_COMPRESSION_RATIO = 100.0

#: A single entry whose own ratio clears this is individually bomb-prone even if the
#: archive's aggregate totals are still under the caps above — a small archive with one
#: absurdly-compressing entry should not have to wait for the aggregate check to catch it.
MAX_PER_ENTRY_COMPRESSION_RATIO = 300.0

#: Extensions that mean "this entry is itself another archive." Deliberately excludes
#: office-document formats (`.docx`/`.xlsx`/`.pptx`) even though they are technically zip
#: containers too — those are legitimate, common receipt attachments, and flagging every one
#: of them as a nested-archive bomb risk would make this check useless in practice. A real
#: nested *generic* archive is a much rarer, much more specifically suspicious shape.
NESTED_ARCHIVE_EXTENSIONS = frozenset({".zip", ".rar", ".7z", ".gz", ".tar", ".tgz", ".jar"})


def check(content: bytes) -> BombCheckResult:
    """The container-level check. `content` bytes never leave memory and are never
    decompressed here — only `infolist()`'s own metadata is read."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        return BombCheckResult(safe=False, reason=f"not a valid zip container: {exc}")

    entry_count = len(infos)
    total_uncompressed = sum(info.file_size for info in infos)
    total_compressed = sum(info.compress_size for info in infos)
    ratio = total_uncompressed / total_compressed if total_compressed else float(total_uncompressed)

    bad_entries = tuple(
        info.filename for info in infos if _entry_is_bad(info)
    )

    reasons: list[str] = []
    if entry_count > MAX_ENTRY_COUNT:
        reasons.append(f"{entry_count} entries exceeds the {MAX_ENTRY_COUNT} cap")
    if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
        reasons.append(
            f"{total_uncompressed} total uncompressed bytes exceeds the "
            f"{MAX_TOTAL_UNCOMPRESSED_BYTES} cap"
        )
    if ratio > MAX_AGGREGATE_COMPRESSION_RATIO:
        reasons.append(f"aggregate compression ratio {ratio:.1f}:1 exceeds the "
                        f"{MAX_AGGREGATE_COMPRESSION_RATIO:.0f}:1 cap")

    return BombCheckResult(
        safe=not reasons,
        reason="; ".join(reasons),
        entry_count=entry_count,
        total_uncompressed_bytes=total_uncompressed,
        compression_ratio=ratio,
        bad_entries=bad_entries,
    )


def _entry_is_bad(info: zipfile.ZipInfo) -> bool:
    per_entry_ratio = info.file_size / info.compress_size if info.compress_size else float(info.file_size)
    if per_entry_ratio > MAX_PER_ENTRY_COMPRESSION_RATIO:
        return True
    lowered = info.filename.lower()
    return any(lowered.endswith(ext) for ext in NESTED_ARCHIVE_EXTENSIONS)


def remediate_or_reject(
    content: bytes,
    bad_members: Sequence[str],
    *,
    zip_cls: type[zipfile.ZipFile] = zipfile.ZipFile,
) -> tuple[bytes, RemediationResult]:
    """§3.1's own resolution: strip just the bad members on Python new enough to do it,
    otherwise the existing safe default applies and the whole archive is rejected.

    `hasattr(zip_cls, "remove")` is feature detection, not a version check
    (`docs/PRINCIPLES.md` §3.3 point 2) — `zipfile.ZipFile.remove()`/`.repack()` are a
    currently-alpha Python 3.16 API that could still shift shape before its stable release,
    and a hard version check would need updating if it does where this check just naturally
    stops matching. `zip_cls` is injectable so a test can exercise the "capability present"
    branch (a fake class exposing the same two methods) on an interpreter that does not
    actually have it yet, the same way the Forward-Compatibility Pattern's own validation
    story works elsewhere in this project.
    """
    if not bad_members:
        return content, RemediationResult(action="not_needed")

    if not hasattr(zip_cls, "remove"):
        return content, RemediationResult(action="rejected_whole_archive")

    buffer = io.BytesIO(content)
    with zip_cls(buffer, "a") as archive:
        for name in bad_members:
            archive.remove(name)
        archive.repack()
    return buffer.getvalue(), RemediationResult(
        action="stripped_and_extracted", removed=tuple(bad_members)
    )


__all__ = [
    "MAX_AGGREGATE_COMPRESSION_RATIO",
    "MAX_ENTRY_COUNT",
    "MAX_PER_ENTRY_COMPRESSION_RATIO",
    "MAX_TOTAL_UNCOMPRESSED_BYTES",
    "NESTED_ARCHIVE_EXTENSIONS",
    "check",
    "remediate_or_reject",
]

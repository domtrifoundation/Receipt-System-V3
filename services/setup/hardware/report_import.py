"""CPU-Z/HWiNFO external report import — the accuracy fallback (deep-dive §5.3).

WMI's own GPU shader/core-count reporting is unreliable in a way VRAM's registry fallback
(`detect.py`) does not fully compensate for. When a CPU-Z or HWiNFO text report is available —
common, standard diagnostic tools a user may already have run — this module extracts real
hardware-read core counts from it and overrides the OS probe's own count for any matching
adapter. Best-effort throughout: a report that cannot be parsed, or that names no adapter the
profile already has, changes nothing rather than raising.

**Consent lives in the wizard, not here** (§5.3's own `dev`/normal asymmetry — inverted from
§4.1's installer-choice prompt: there, dev mode double-checks; here, normal mode does, because
normal mode's whole design goal is a transparent first impression). This module only does the
scanning and merging once asked; it never decides on its own whether to look.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from pathlib import Path

from ..contracts import GpuInfo, HardwareProfile

__all__ = [
    "DEFAULT_CANDIDATE_DIRS",
    "find_and_merge",
    "parse_report_text",
]

#: Where CPU-Z/HWiNFO reports are conventionally saved by those tools' own default export
#: behaviour — Documents is the one directory both tools default to. `Path.home()` rather than
#: a hardcoded OS-specific path, since both tools resolve "Documents" the same way the OS does.
DEFAULT_CANDIDATE_DIRS: tuple[Path, ...] = (Path.home() / "Documents",)

#: A bare block-start marker — CPU-Z's real export puts nothing but "GPU 1" on this line; the
#: adapter's actual name is a separate field a few lines further down the same block, not part
#: of the header itself. (An earlier version of this parser assumed the name lived on the
#: header line — wrong, and caught by this module's own tests against a realistic fixture.)
_BLOCK_START = re.compile(r"^\s*(?:GPU|Display\s*Adapter)\s*\d+\s*$", re.IGNORECASE)

#: Label/value separator is deliberately permissive — a colon (HWiNFO's own ini-like style), a
#: dash, or CPU-Z's real column-padded run of 2+ spaces/tabs all appear across real exports from
#: these two tools, and neither format is formally specified enough to commit to one separator.
_NAME_LINE = re.compile(r"^\s*Name\s*(?:[:\-]|\s{2,})\s*(?P<name>.+?)\s*$", re.IGNORECASE)
_CORE_COUNT_LINE = re.compile(
    r"^\s*(?:Shaders?|Shader\s*Processors?|Stream\s*Processors?|Unified\s*Shaders?)\b"
    r"[^0-9]*(?P<count>\d+)\s*$",
    re.IGNORECASE,
)


def parse_report_text(text: str) -> dict[str, int]:
    """Extracts `{adapter_name_lowercased: real_core_count}` from one report's raw text.

    A best-effort block scanner rather than a strict grammar: neither tool's export format is
    formally specified and both drift release to release, and a report this cannot fully parse
    should still yield whatever adapters it could read rather than nothing at all. A block is
    committed to the result once both its `Name` and its shader/core count line have been seen,
    regardless of which order they appear in within the block.
    """
    found: dict[str, int] = {}
    current_name: str | None = None
    current_count: int | None = None

    def commit() -> None:
        if current_name is not None and current_count is not None:
            found[current_name.lower()] = current_count

    for line in text.splitlines():
        if _BLOCK_START.match(line):
            commit()
            current_name = None
            current_count = None
            continue

        name_match = _NAME_LINE.match(line)
        if name_match:
            current_name = name_match.group("name").strip()
            continue

        count_match = _CORE_COUNT_LINE.match(line)
        if count_match:
            current_count = int(count_match.group("count"))

    commit()
    return found


def _merge_core_counts(profile: HardwareProfile, core_counts: dict[str, int]) -> HardwareProfile:
    """Substring match, not equality: a report's own adapter name ("NVIDIA GeForce RTX 4090")
    and WMI's own name for the same card rarely match character-for-character, but one reliably
    contains a recognizable fragment of the other."""
    if not core_counts:
        return profile

    updated_gpus: list[GpuInfo] = []
    contributed = False
    for gpu in profile.gpus:
        gpu_lower = gpu.name.lower()
        match = next(
            (
                count
                for report_name, count in core_counts.items()
                if report_name in gpu_lower or gpu_lower in report_name
            ),
            None,
        )
        if match is not None:
            updated_gpus.append(replace(gpu, shader_core_count=match))
            contributed = True
        else:
            updated_gpus.append(gpu)

    if not contributed:
        return profile

    return replace(profile, gpus=tuple(updated_gpus), source=f"{profile.source}+external_report")


async def find_and_merge(profile: HardwareProfile, search_paths: tuple[Path, ...]) -> HardwareProfile:
    """Looks for a CPU-Z/HWiNFO report in `search_paths`, merges what it finds into `profile`.

    Merges across every readable report found rather than stopping at the first (§5.3: "merging
    across multiple report files if more than one is found"). Best-effort throughout — an
    unreadable file is skipped, not fatal to the whole operation.

    File I/O is dispatched via `run_in_executor`, matching `detect.py`'s own convention for this
    package — §8.1's own assessment is that the actual volume here is trivially small (Setup
    never runs many of these in parallel), so this is about consistency within the package
    rather than a real performance requirement.
    """
    loop = asyncio.get_running_loop()
    combined_counts = await loop.run_in_executor(None, _scan_reports, search_paths)
    return _merge_core_counts(profile, combined_counts)


def _scan_reports(search_paths: tuple[Path, ...]) -> dict[str, int]:
    combined_counts: dict[str, int] = {}
    for directory in search_paths:
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.glob("*.txt")):
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            combined_counts.update(parse_report_text(text))
    return combined_counts

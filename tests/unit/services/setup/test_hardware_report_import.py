"""CPU-Z/HWiNFO external report import (`v3-deepdive-11-setup-api.md` §5.3).

A genuine accuracy improvement over the OS probe, not a redundant feature — this pins the
merge behaviour real files on disk, since the whole point of this module is reading real files a
user may have already generated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from services.setup.contracts import GpuInfo, HardwareProfile
from services.setup.hardware.report_import import find_and_merge, parse_report_text

#: Deliberately shaped like a real CPU-Z .txt export, not an idealized "Key : Value" fixture:
#: the adapter's name is a separate `Name` field within the block, not part of the "GPU 1"
#: header line itself, and fields are column-padded with spaces rather than colon-separated.
_CPUZ_STYLE_REPORT = """\
CPU-Z TXT Report
-------------------------------------------------------------------------

Display Adapters
-------------------------------------------------------------------------
GPU 1
\tName                  NVIDIA GeForce RTX 4090
\tCodename                        AD102
\tShaders (Cores)                    16384

GPU 2
\tName                  Intel(R) UHD Graphics 770
\tShaders (Cores)                       32
"""


def _profile(gpus):
    return HardwareProfile(
        cpu_name="Test CPU",
        cores=8,
        threads=16,
        ram_gb=32,
        gpus=tuple(gpus),
        npus=(),
        detected_at=datetime.now(timezone.utc),
        source="os_probe",
    )


def test_parses_shader_counts_keyed_by_lowercased_adapter_name():
    result = parse_report_text(_CPUZ_STYLE_REPORT)
    assert result.get("nvidia geforce rtx 4090") == 16384
    assert result.get("intel(r) uhd graphics 770") == 32


def test_a_report_naming_no_known_adapter_leaves_the_profile_unchanged():
    """Best-effort per §5.3 — a report is not required to be relevant to this machine."""
    gpu = GpuInfo(name="Totally Different GPU", vendor="unknown", discrete=True, vram_gb=None, compute_api="unknown")
    original = _profile([gpu])

    merged = _merge_via_module(original, "GPU 1\nName : Some Other Card\nShaders : 999\n")

    assert merged.gpus[0].shader_core_count is None
    assert merged.source == "os_probe"


def test_a_matching_adapter_gets_its_shader_count_filled_in_and_source_updated():
    gpu = GpuInfo(name="NVIDIA GeForce RTX 4090", vendor="nvidia", discrete=True, vram_gb=24.0, compute_api="cuda")
    original = _profile([gpu])

    merged = _merge_via_module(original, _CPUZ_STYLE_REPORT)

    assert merged.gpus[0].shader_core_count == 16384
    assert merged.source == "os_probe+external_report"


def test_matching_is_substring_based_not_exact_equality():
    """A report's own adapter name and WMI's name for the same card rarely match
    character-for-character — this is the realistic case, not the exact-match happy path.
    """
    gpu = GpuInfo(name="Intel(R) UHD Graphics 770", vendor="intel", discrete=False, vram_gb=1.0, compute_api="sycl")
    original = _profile([gpu])

    merged = _merge_via_module(original, _CPUZ_STYLE_REPORT)

    assert merged.gpus[0].shader_core_count == 32


def _merge_via_module(profile: HardwareProfile, report_text: str) -> HardwareProfile:
    """No `pytest-asyncio` in this repo by convention — a small `asyncio.run` helper instead."""
    import asyncio
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "cpuz_report.txt"
        report_path.write_text(report_text, encoding="utf-8")
        return asyncio.run(find_and_merge(profile, (Path(tmp),)))


def test_multiple_report_files_in_the_search_path_are_all_merged():
    """§5.3: "merging across multiple report files if more than one is found" — not just the
    first one encountered.
    """
    gpu_a = GpuInfo(name="NVIDIA GeForce RTX 4090", vendor="nvidia", discrete=True, vram_gb=24.0, compute_api="cuda")
    gpu_b = GpuInfo(name="Intel(R) UHD Graphics 770", vendor="intel", discrete=False, vram_gb=1.0, compute_api="sycl")
    original = _profile([gpu_a, gpu_b])

    import asyncio
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.txt").write_text("GPU 1\nName : NVIDIA GeForce RTX 4090\nShaders : 16384\n", encoding="utf-8")
        (Path(tmp) / "b.txt").write_text("GPU 1\nName : Intel(R) UHD Graphics 770\nShaders : 32\n", encoding="utf-8")
        merged = asyncio.run(find_and_merge(original, (Path(tmp),)))

    assert merged.gpus[0].shader_core_count == 16384
    assert merged.gpus[1].shader_core_count == 32


def test_a_nonexistent_search_directory_is_skipped_not_an_error():
    gpu = GpuInfo(name="Test GPU", vendor="unknown", discrete=True, vram_gb=None, compute_api="unknown")
    original = _profile([gpu])

    import asyncio

    result = asyncio.run(find_and_merge(original, (Path("/does/not/exist/at/all"),)))
    assert result == original

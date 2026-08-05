"""`hardware/persistence.py` — real disk round-trips, the previously-missing half of §8.6:
`DetectHardware` always re-probed live and returned over gRPC, but nothing ever wrote the
result anywhere for another process (`core/health/resource_ledger.py`'s own
`HardwareProfileReader`, in particular) to read later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from services.setup.contracts import GpuInfo, HardwareProfile
from services.setup.hardware.persistence import (
    HARDWARE_PROFILE_RELPATH,
    read_hardware_profile,
    write_hardware_profile,
)


def _real_profile() -> HardwareProfile:
    return HardwareProfile(
        cpu_name="Intel(R) Core(TM) i9",
        cores=16,
        threads=24,
        ram_gb=64,
        gpus=(
            GpuInfo(
                name="Intel(R) Arc(TM) B580 Graphics", vendor="intel", discrete=True,
                vram_gb=11.9, compute_api="sycl", shader_core_count=None,
            ),
        ),
        npus=(),
        detected_at=datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc),
        source="os_probe",
    )


def test_read_returns_none_when_nothing_was_ever_written(tmp_path: Path):
    assert read_hardware_profile(tmp_path) is None


def test_write_then_read_round_trips_every_real_field(tmp_path: Path):
    original = _real_profile()

    write_hardware_profile(tmp_path, original)
    restored = read_hardware_profile(tmp_path)

    assert restored == original


def test_write_creates_the_documented_relative_path(tmp_path: Path):
    write_hardware_profile(tmp_path, _real_profile())

    assert (tmp_path / HARDWARE_PROFILE_RELPATH).is_file()


def test_second_write_overwrites_rather_than_write_once(tmp_path: Path):
    """Real, deliberate asymmetry vs. `install.json`'s write-once `dev_mode`: hardware can
    genuinely change across a reinstall, so every detection re-writes."""
    write_hardware_profile(tmp_path, _real_profile())

    changed = HardwareProfile(
        cpu_name="A different CPU", cores=4, threads=8, ram_gb=16, gpus=(), npus=(),
        detected_at=datetime(2026, 9, 1, tzinfo=timezone.utc), source="os_probe",
    )
    write_hardware_profile(tmp_path, changed)

    assert read_hardware_profile(tmp_path) == changed


def test_read_degrades_to_none_on_a_corrupt_file(tmp_path: Path):
    target = tmp_path / HARDWARE_PROFILE_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not valid json", encoding="utf-8")

    assert read_hardware_profile(tmp_path) is None


def test_profile_with_no_gpus_and_no_ram_round_trips(tmp_path: Path):
    """The real degrade-gracefully shape `detect.py` itself can produce: a machine with
    zero detected GPUs, or a probe that could not read RAM at all."""
    profile = HardwareProfile(
        cpu_name="unknown", cores=0, threads=0, ram_gb=None, gpus=(), npus=(),
        detected_at=datetime(2026, 8, 5, tzinfo=timezone.utc), source="os_probe",
    )

    write_hardware_profile(tmp_path, profile)

    assert read_hardware_profile(tmp_path) == profile

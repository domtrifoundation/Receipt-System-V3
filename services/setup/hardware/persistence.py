"""Persists a detected `HardwareProfile` to disk so a process other than the one that ran
`DetectHardware` can read it — the real, previously-missing half of §8.6's own design.

**A real, live-found gap, not a documented placeholder.** `DetectHardware`
(`services/setup/service.py`) re-probes hardware live on every call and returns it over
gRPC, but nothing ever wrote the result anywhere — confirmed by grep, zero matches for
anything resembling a persisted hardware profile anywhere in this repo before this file.
`core/health/resource_ledger.py`'s own `HardwareProfileReader` Protocol has been waiting
for exactly this since it was built: *"Setup API does not exist yet, so the default reader
publishes nothing... when Setup API lands, wiring it in means passing a real reader here."*
This is that landing.

**Always overwrites, unlike `install.json`'s write-once `dev_mode`.** Hardware genuinely
can change across a reinstall on the same install root (a GPU swap, more RAM) — the
`HardwareProfile.detected_at` field is exactly what makes "stale" a real, checkable
concept, and holding onto a stale profile serves nobody. Every real `DetectHardware` call
re-writes the file with what it just found.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..contracts import GpuInfo, HardwareProfile

__all__ = ["HARDWARE_PROFILE_RELPATH", "read_hardware_profile", "write_hardware_profile"]

HARDWARE_PROFILE_RELPATH = Path("config") / "hardware_profile.json"


def _gpu_to_dict(gpu: GpuInfo) -> dict:
    return {
        "name": gpu.name,
        "vendor": gpu.vendor,
        "discrete": gpu.discrete,
        "vram_gb": gpu.vram_gb,
        "compute_api": gpu.compute_api,
        "shader_core_count": gpu.shader_core_count,
    }


def _gpu_from_dict(data: dict) -> GpuInfo:
    return GpuInfo(
        name=str(data.get("name", "")),
        vendor=str(data.get("vendor", "unknown")),
        discrete=bool(data.get("discrete", False)),
        vram_gb=data.get("vram_gb"),
        compute_api=str(data.get("compute_api", "unknown")),
        shader_core_count=data.get("shader_core_count"),
    )


def write_hardware_profile(install_root: Path, profile: HardwareProfile) -> None:
    target = install_root / HARDWARE_PROFILE_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cpu_name": profile.cpu_name,
        "cores": profile.cores,
        "threads": profile.threads,
        "ram_gb": profile.ram_gb,
        "gpus": [_gpu_to_dict(g) for g in profile.gpus],
        "npus": list(profile.npus),
        "detected_at": profile.detected_at.isoformat(),
        "source": profile.source,
    }
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_hardware_profile(install_root: Path) -> HardwareProfile | None:
    """`None` when nothing has been detected/persisted yet (a self-hosted install before
    its first-run wizard, or a Linux dev checkout) or the file is corrupt — a caller
    (`core/health/resource_ledger.py`'s own reader, in particular) degrades from that the
    same way it already degrades from Setup API not existing at all: every reservation
    against an unknown device is rejected, never a crash (§4.2's fail-closed posture).
    """
    target = install_root / HARDWARE_PROFILE_RELPATH
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        detected_at = datetime.fromisoformat(data["detected_at"])
        if detected_at.tzinfo is None:
            detected_at = detected_at.replace(tzinfo=timezone.utc)
        return HardwareProfile(
            cpu_name=str(data.get("cpu_name", "unknown")),
            cores=int(data.get("cores", 0)),
            threads=int(data.get("threads", 0)),
            ram_gb=data.get("ram_gb"),
            gpus=tuple(_gpu_from_dict(g) for g in data.get("gpus", [])),
            npus=tuple(data.get("npus", ())),
            detected_at=detected_at,
            source=str(data.get("source", "os_probe")),
        )
    except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
        return None

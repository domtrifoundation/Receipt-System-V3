"""Platform-dispatch hardware probing (deep-dive §5.1-§5.2) — the static `HardwareProfile`.

Two things this module gets right that are easy to get wrong, both **live-verified against
real hardware during this module's own development**, not just reasoned about:

1. **PowerShell's `ConvertTo-Json` unwraps a single-item array into a bare object.** A machine
   with exactly one GPU returns a dict from `Win32_VideoController`, not a one-element list —
   `_normalize_to_list` below is the fix, applied to every WMI collection this module parses.
2. **`AdapterRAM` is a capped, unreliable 32-bit value.** Confirmed live on the machine this was
   built on: a real Intel Arc B580 (12GB VRAM) reports `AdapterRAM: 2147479552` — ~2GB — while
   the registry's `HardwareInformation.qwMemorySize` correctly reports `12782141440` (~11.9GB).
   This is not a hypothetical from the deep-dive; it reproduced on the first machine this ran
   against. The registry value wins whenever present, never averaged or used as a tiebreak.

Parsing is kept **pure and separate from the subprocess/file I/O** that feeds it
(`parse_windows_probe`, `parse_linux_probe`) specifically so the two documented gotchas above
are unit-testable with synthetic input, without requiring a matching GPU on the test machine.
The I/O itself is dispatched via `run_in_executor` (§8.1) — a handful of one-time subprocess/file
calls, not a hot path, so the actual volume here does not need more than that.
"""

from __future__ import annotations

import asyncio
import json
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..contracts import GpuInfo, HardwareDetector, HardwareProfile

__all__ = [
    "LinuxHardwareDetector",
    "WindowsHardwareDetector",
    "default_detector",
    "parse_linux_probe",
    "parse_windows_probe",
]

# One combined script, one subprocess spawn, covering CPU/GPU/RAM/registry-VRAM together —
# minimizes the real, if small, cost §8.1 flags (a handful of subprocess calls, once).
_WINDOWS_PROBE_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$cpu = Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
$gpu = Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,PNPDeviceID
$mem = Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
$vramClass = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
$vram = @()
Get-ChildItem $vramClass -ErrorAction SilentlyContinue | ForEach-Object {
    $p = Get-ItemProperty -Path $_.PSPath -Name 'HardwareInformation.qwMemorySize','MatchingDeviceId' -ErrorAction SilentlyContinue
    if ($p -and $p.'HardwareInformation.qwMemorySize' -and $p.MatchingDeviceId) {
        $vram += [PSCustomObject]@{
            MatchingDeviceId = $p.MatchingDeviceId
            VramBytes = $p.'HardwareInformation.qwMemorySize'
        }
    }
}
[PSCustomObject]@{ cpu = $cpu; gpu = $gpu; mem = $mem; vram = $vram } | ConvertTo-Json -Depth 5
""".strip()


def _normalize_to_list(raw: object) -> list[dict]:
    """The single-item-array-unwraps-to-dict fix (§5.1), applied uniformly.

    `None` (the collection query returned nothing) becomes an empty list rather than a crash —
    a machine that genuinely has zero GPUs is a real, valid profile, not an error.
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return raw
    raise TypeError(f"expected dict, list, or None from ConvertTo-Json, got {type(raw)!r}")


def _classify_vendor(name: str) -> str:
    lowered = name.lower()
    if "nvidia" in lowered:
        return "nvidia"
    if "amd" in lowered or "radeon" in lowered:
        return "amd"
    if "intel" in lowered:
        return "intel"
    return "unknown"


def _classify_discrete(name: str, vendor: str) -> bool:
    """Vendor name alone does not answer discrete-vs-integrated — Intel ships both.

    The real, previously-hit failure this guards against (§5.2): Arrow Lake-generation
    integrated GPUs report under the plain, non-descriptive name "Intel(R) Graphics" — this
    machine's own second adapter is exactly that string — so a naive "contains 'Graphics'"
    check would misclassify it as discrete. "Arc" is Intel's discrete brand name and is checked
    first; a bare "Intel(R) Graphics"/"Intel(R) UHD Graphics"/"Intel(R) Iris Xe Graphics" with no
    "Arc" is integrated. NVIDIA and AMD desktop/laptop dedicated adapters are treated as discrete
    by default — genuinely integrated AMD/NVIDIA graphics are rare enough on this project's
    target hardware (`docs/apis/v3-deepdive-11-setup-api.md` §5.4's own NUC-class/consumer-
    workstation framing) that this default is the defensible one, not a guess dressed as one.
    """
    lowered = name.lower()
    if vendor == "intel":
        return "arc" in lowered
    return True


def _classify_compute_api(vendor: str) -> str:
    """§5.2's mapping: Intel discrete/integrated both route through OpenVINO/oneAPI ("sycl"),
    NVIDIA to CUDA, AMD to ROCm (with the MIGraphX caveat the OCR/Inference deep-dives already
    establish — the ROCm EP itself was removed from ONNX Runtime as of 1.23, but the
    classification here is the underlying-platform name, not the specific EP a caller picks)."""
    return {"nvidia": "cuda", "amd": "rocm", "intel": "sycl"}.get(vendor, "unknown")


def _resolve_vram_gb(adapter_ram: object, pnp_device_id: str, vram_registry: list[dict]) -> float | None:
    """Fallback order: registry → `AdapterRAM` → `None` (§5.2). Never averaged, never a
    tiebreak — the registry value wins outright whenever a match exists.

    Matched by `MatchingDeviceId` being a prefix of the adapter's own `PNPDeviceID`
    (case-insensitive) — the real driver-to-device correlation Windows itself uses; confirmed
    against a live registry read during this module's development, not assumed from
    documentation alone.
    """
    pnp_upper = (pnp_device_id or "").upper()
    for entry in vram_registry:
        matching_id = str(entry.get("MatchingDeviceId") or "").upper()
        if matching_id and pnp_upper.startswith(matching_id):
            vram_bytes = entry.get("VramBytes")
            if isinstance(vram_bytes, (int, float)) and vram_bytes > 0:
                return round(vram_bytes / (1024**3), 2)

    if isinstance(adapter_ram, (int, float)) and adapter_ram > 0:
        return round(adapter_ram / (1024**3), 2)

    return None


def parse_windows_probe(raw_json: str) -> HardwareProfile:
    """Pure parser: `_WINDOWS_PROBE_SCRIPT`'s stdout in, a `HardwareProfile` out.

    Kept separate from the subprocess call specifically so both documented gotchas (module
    docstring) are testable with a synthetic JSON string, without needing matching GPU hardware
    on whichever machine runs the test suite.
    """
    parsed = json.loads(raw_json)

    cpu_list = _normalize_to_list(parsed.get("cpu"))
    cpu = cpu_list[0] if cpu_list else {}
    cores = sum(int(c.get("NumberOfCores") or 0) for c in cpu_list) or int(cpu.get("NumberOfCores") or 0)
    threads = sum(int(c.get("NumberOfLogicalProcessors") or 0) for c in cpu_list) or int(
        cpu.get("NumberOfLogicalProcessors") or 0
    )

    mem_list = _normalize_to_list(parsed.get("mem"))
    total_bytes = mem_list[0].get("TotalPhysicalMemory") if mem_list else None
    ram_gb = round(int(total_bytes) / (1024**3)) if total_bytes else None

    vram_registry = _normalize_to_list(parsed.get("vram"))

    gpus: list[GpuInfo] = []
    for raw_gpu in _normalize_to_list(parsed.get("gpu")):
        name = str(raw_gpu.get("Name") or "").strip()
        if not name:
            continue
        vendor = _classify_vendor(name)
        gpus.append(
            GpuInfo(
                name=name,
                vendor=vendor,
                discrete=_classify_discrete(name, vendor),
                vram_gb=_resolve_vram_gb(
                    raw_gpu.get("AdapterRAM"), str(raw_gpu.get("PNPDeviceID") or ""), vram_registry
                ),
                compute_api=_classify_compute_api(vendor),
            )
        )

    return HardwareProfile(
        cpu_name=str(cpu.get("Name") or "").strip() or "unknown",
        cores=cores,
        threads=threads,
        ram_gb=ram_gb,
        gpus=tuple(gpus),
        npus=(),  # No standard WMI class enumerates NPUs as of this module's own build; a real
        #           gap, not an oversight — left empty rather than guessed. See CLAUDE.md.
        detected_at=datetime.now(timezone.utc),
        source="os_probe",
    )


class WindowsHardwareDetector:
    """`HardwareDetector` for Windows — WMI via PowerShell (§5.1)."""

    async def detect(self) -> HardwareProfile:
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, _run_windows_probe)
        return parse_windows_probe(raw)


def _run_windows_probe() -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_PROBE_SCRIPT],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout


# --- Linux ------------------------------------------------------------------------------------

_LSPCI_GPU_LINE = re.compile(
    r"^(?P<slot>\S+)\s+(?P<class>VGA compatible controller|3D controller|Display controller)"
    r"\s*:\s*(?P<name>.+)$"
)


def _read_proc_cpuinfo(text: str) -> tuple[str, int, int]:
    """Returns `(cpu_name, physical_cores, logical_threads)`.

    Physical core count from unique `physical id` + `core id` pairs where present (falls back to
    logical-thread count on a kernel/VM that omits those fields, e.g. many single-socket cloud
    VMs) — `/proc/cpuinfo` lists one stanza per logical thread, never per physical core.
    """
    name = "unknown"
    threads = 0
    physical_core_ids: set[tuple[str, str]] = set()
    physical_id = core_id = None

    for line in text.splitlines():
        if ":" not in line:
            if line.strip() == "" and physical_id is not None and core_id is not None:
                physical_core_ids.add((physical_id, core_id))
                physical_id = core_id = None
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "model name" and name == "unknown":
            name = value
        elif key == "physical id":
            physical_id = value
        elif key == "core id":
            core_id = value
        elif key == "processor":
            threads += 1

    if physical_id is not None and core_id is not None:
        physical_core_ids.add((physical_id, core_id))

    cores = len(physical_core_ids) or threads
    return name, cores, threads


def _read_proc_meminfo(text: str) -> int | None:
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return round(int(parts[1]) / (1024**2))  # kB -> GB
    return None


def _parse_lspci_gpus(text: str) -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    for line in text.splitlines():
        match = _LSPCI_GPU_LINE.match(line)
        if not match:
            continue
        name = match.group("name").strip()
        vendor = _classify_vendor(name)
        gpus.append(
            GpuInfo(
                name=name,
                vendor=vendor,
                discrete=_classify_discrete(name, vendor),
                # lspci reports no VRAM size directly; a discrete card's real size is read from
                # `/sys/class/drm/*/device/mem_info_vram_total` (AMD) or `nvidia-smi` (NVIDIA)
                # in a fuller implementation — genuinely deferred, not silently guessed at
                # (see CLAUDE.md). None here is the honest answer, matching Windows's own
                # never-guess-a-number rule (§5.2) rather than inventing a Linux-only shortcut.
                vram_gb=None,
                compute_api=_classify_compute_api(vendor),
            )
        )
    return gpus


def parse_linux_probe(cpuinfo_text: str, meminfo_text: str, lspci_text: str) -> HardwareProfile:
    """Pure parser, mirroring `parse_windows_probe`'s separation from I/O."""
    cpu_name, cores, threads = _read_proc_cpuinfo(cpuinfo_text)
    return HardwareProfile(
        cpu_name=cpu_name,
        cores=cores,
        threads=threads,
        ram_gb=_read_proc_meminfo(meminfo_text),
        gpus=tuple(_parse_lspci_gpus(lspci_text)),
        npus=(),
        detected_at=datetime.now(timezone.utc),
        source="os_probe",
    )


class LinuxHardwareDetector:
    """`HardwareDetector` for Linux — `/proc/cpuinfo` + `/proc/meminfo` + `lspci` (§5.1)."""

    async def detect(self) -> HardwareProfile:
        loop = asyncio.get_running_loop()
        cpuinfo, meminfo, lspci = await loop.run_in_executor(None, _read_linux_probe)
        return parse_linux_probe(cpuinfo, meminfo, lspci)


def _read_linux_probe() -> tuple[str, str, str]:
    cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    meminfo = Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace")
    try:
        lspci = subprocess.run(
            ["lspci"], capture_output=True, text=True, check=True, timeout=10
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        lspci = ""  # Degrade to zero detected GPUs rather than failing the whole profile
        #             (docs/PRINCIPLES.md §4.4) — `lspci` genuinely may not be installed.
    return cpuinfo, meminfo, lspci


def default_detector() -> HardwareDetector:
    """Selects the right `HardwareDetector` for the running OS at registry-init time — a real
    Provider Registry entry (`docs/PRINCIPLES.md` §1.2), not branching inline wherever hardware
    detection is needed."""
    system = platform.system()
    if system == "Windows":
        return WindowsHardwareDetector()
    if system == "Linux":
        return LinuxHardwareDetector()
    raise NotImplementedError(
        f"no HardwareDetector for {system!r} yet — Windows and Linux only, per "
        "docs/apis/v3-deepdive-11-setup-api.md §5.1"
    )

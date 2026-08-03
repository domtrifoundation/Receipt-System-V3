"""Hardware detection's own parsers (`v3-deepdive-11-setup-api.md` §5.1-§5.2).

§9 names both gotchas below as deserving their own explicit regression tests, "given they're
real, previously-hit bugs, not hypothetical edge cases — a regression here would silently
degrade every downstream hardware-acceleration decision across three other APIs without
necessarily failing loudly." The synthetic JSON here is not invented for the occasion — it is
the exact shape this module's own live run against real hardware produced during development:
a real Intel Arc B580 whose `AdapterRAM` under-reports by roughly 6x, and a real integrated
"Intel(R) Graphics" adapter with no brand-distinguishing name at all.
"""

from __future__ import annotations

import json

from services.setup.hardware.detect import (
    parse_linux_probe,
    parse_windows_probe,
)


def _windows_probe(cpu, gpu, mem, vram):
    return json.dumps({"cpu": cpu, "gpu": gpu, "mem": mem, "vram": vram})


def test_a_single_gpu_machine_does_not_crash_on_the_dict_not_list_unwrap():
    """PowerShell's `ConvertTo-Json` returns a bare object, not a one-element array, when a WMI
    query returns exactly one row — a machine with one GPU is the common case, not the edge
    case, so getting this wrong breaks detection for most real machines rather than a rare one.
    """
    raw = _windows_probe(
        cpu={"Name": "Test CPU", "NumberOfCores": 8, "NumberOfLogicalProcessors": 16},
        gpu={"Name": "Test GPU", "AdapterRAM": 4294967295, "PNPDeviceID": "PCI\\VEN_TEST"},
        mem={"TotalPhysicalMemory": 34359738368},
        vram=[],
    )
    profile = parse_windows_probe(raw)

    assert len(profile.gpus) == 1
    assert profile.gpus[0].name == "Test GPU"
    assert profile.cores == 8
    assert profile.ram_gb == 32


def test_a_zero_gpu_machine_is_a_valid_profile_not_a_crash():
    """`ConvertTo-Json` on an empty collection query yields `null`/`None`, not `[]` — a distinct
    shape from the single-item case, and one the parser must also degrade cleanly on.
    """
    raw = _windows_probe(
        cpu={"Name": "Test CPU", "NumberOfCores": 4, "NumberOfLogicalProcessors": 4},
        gpu=None,
        mem={"TotalPhysicalMemory": 8589934592},
        vram=None,
    )
    profile = parse_windows_probe(raw)

    assert profile.gpus == ()
    assert profile.cpu_name == "Test CPU"


def test_the_registry_vram_value_wins_over_adapter_ram_never_averaged():
    """The exact bug named in §5.2, reproduced from a real live probe during this module's own
    development: a genuine Intel Arc B580 (12GB VRAM) reported `AdapterRAM: 2147479552` (~2GB)
    while the registry's own `HardwareInformation.qwMemorySize` correctly reported
    `12782141440` (~11.9GB). This is not a synthesized worst case — it is what this machine's
    real WMI query actually returned.
    """
    pnp_id = "PCI\\VEN_8086&DEV_E20B&SUBSYS_11008086&REV_00\\6&1709B71B&0&00080030"
    raw = _windows_probe(
        cpu={"Name": "Intel(R) Core(TM) Ultra 9 285K", "NumberOfCores": 24, "NumberOfLogicalProcessors": 24},
        gpu={"Name": "Intel(R) Arc(TM) B580 Graphics", "AdapterRAM": 2147479552, "PNPDeviceID": pnp_id},
        mem={"TotalPhysicalMemory": 103079215104},
        vram=[{"MatchingDeviceId": "PCI\\VEN_8086&DEV_E20B&SUBSYS_11008086", "VramBytes": 12782141440}],
    )
    profile = parse_windows_probe(raw)

    assert profile.gpus[0].vram_gb == 11.9
    assert profile.gpus[0].vram_gb != 2.0, "AdapterRAM's undercounted value leaked through"


def test_adapter_ram_is_the_fallback_when_no_registry_entry_matches():
    """Not every adapter has a `qwMemorySize` registry entry — a real integrated GPU sharing
    system RAM typically does not. The fallback chain is registry -> AdapterRAM -> None, and
    this pins the middle rung: AdapterRAM is trusted when it is genuinely the only signal, not
    discarded just because it is sometimes wrong for other adapters.
    """
    raw = _windows_probe(
        cpu={"Name": "Test CPU", "NumberOfCores": 8, "NumberOfLogicalProcessors": 16},
        gpu={"Name": "Intel(R) Graphics", "AdapterRAM": 2147479552, "PNPDeviceID": "PCI\\VEN_8086&DEV_7D67"},
        mem={"TotalPhysicalMemory": 34359738368},
        vram=[{"MatchingDeviceId": "PCI\\VEN_8086&DEV_E20B", "VramBytes": 12782141440}],  # a different adapter
    )
    profile = parse_windows_probe(raw)

    assert profile.gpus[0].vram_gb == 2.0


def test_vram_is_none_rather_than_a_guess_when_nothing_reports_it():
    raw = _windows_probe(
        cpu={"Name": "Test CPU", "NumberOfCores": 4, "NumberOfLogicalProcessors": 4},
        gpu={"Name": "Some Unknown GPU", "AdapterRAM": 0, "PNPDeviceID": "PCI\\VEN_0000"},
        mem={"TotalPhysicalMemory": 8589934592},
        vram=[],
    )
    profile = parse_windows_probe(raw)

    assert profile.gpus[0].vram_gb is None


def test_an_integrated_intel_adapter_with_a_generic_name_classifies_as_integrated():
    """The real V2 finding named in §5.2: Arrow Lake-generation integrated GPUs report under a
    plain, non-descriptive "Intel(R) Graphics" name with nothing distinguishing them from a
    discrete adapter by name alone. This machine's own live probe reproduced exactly this
    string. A naive "any GPU with a real name is discrete" rule would misclassify it.
    """
    raw = _windows_probe(
        cpu={"Name": "Test CPU", "NumberOfCores": 8, "NumberOfLogicalProcessors": 16},
        gpu={"Name": "Intel(R) Graphics", "AdapterRAM": 2147479552, "PNPDeviceID": "PCI\\VEN_8086"},
        mem={"TotalPhysicalMemory": 17179869184},
        vram=[],
    )
    profile = parse_windows_probe(raw)

    assert profile.gpus[0].vendor == "intel"
    assert profile.gpus[0].discrete is False


def test_an_intel_arc_adapter_classifies_as_discrete():
    raw = _windows_probe(
        cpu={"Name": "Test CPU", "NumberOfCores": 8, "NumberOfLogicalProcessors": 16},
        gpu={"Name": "Intel(R) Arc(TM) B580 Graphics", "AdapterRAM": 2147479552, "PNPDeviceID": "PCI\\VEN_8086"},
        mem={"TotalPhysicalMemory": 17179869184},
        vram=[],
    )
    profile = parse_windows_probe(raw)

    assert profile.gpus[0].discrete is True
    assert profile.gpus[0].compute_api == "sycl"


def test_nvidia_and_amd_classify_to_their_own_compute_apis():
    raw = _windows_probe(
        cpu={"Name": "Test CPU", "NumberOfCores": 8, "NumberOfLogicalProcessors": 16},
        gpu=[
            {"Name": "NVIDIA GeForce RTX 4090", "AdapterRAM": 4294967295, "PNPDeviceID": "PCI\\VEN_10DE"},
            {"Name": "AMD Radeon RX 7900 XTX", "AdapterRAM": 4294967295, "PNPDeviceID": "PCI\\VEN_1002"},
        ],
        mem={"TotalPhysicalMemory": 34359738368},
        vram=[],
    )
    profile = parse_windows_probe(raw)
    by_vendor = {g.vendor: g for g in profile.gpus}

    assert by_vendor["nvidia"].compute_api == "cuda"
    assert by_vendor["nvidia"].discrete is True
    assert by_vendor["amd"].compute_api == "rocm"
    assert by_vendor["amd"].discrete is True


def test_multi_socket_core_and_thread_counts_sum_across_processor_entries():
    """`Win32_Processor` returns one row per physical socket; a dual-socket machine's real core
    count is the sum, not the first row's own count alone.
    """
    raw = _windows_probe(
        cpu=[
            {"Name": "Xeon Gold", "NumberOfCores": 16, "NumberOfLogicalProcessors": 32},
            {"Name": "Xeon Gold", "NumberOfCores": 16, "NumberOfLogicalProcessors": 32},
        ],
        gpu=None,
        mem={"TotalPhysicalMemory": 274877906944},
        vram=None,
    )
    profile = parse_windows_probe(raw)

    assert profile.cores == 32
    assert profile.threads == 64


# --- Linux --------------------------------------------------------------------------------

_CPUINFO_TWO_CORE_FOUR_THREAD = """\
processor\t: 0
model name\t: Test Linux CPU
physical id\t: 0
core id\t: 0

processor\t: 1
model name\t: Test Linux CPU
physical id\t: 0
core id\t: 1

processor\t: 2
model name\t: Test Linux CPU
physical id\t: 0
core id\t: 0

processor\t: 3
model name\t: Test Linux CPU
physical id\t: 0
core id\t: 1
"""

_MEMINFO = "MemTotal:       33554432 kB\nMemFree:         1000000 kB\n"

_LSPCI_ONE_GPU = (
    "00:02.0 VGA compatible controller: Intel Corporation Test Integrated Graphics\n"
    "00:03.0 Audio device: Intel Corporation Test Audio\n"
)


def test_linux_core_count_is_unique_physical_id_core_id_pairs_not_thread_count():
    """`/proc/cpuinfo` lists one stanza per logical thread. Counting stanzas as cores would
    report hyperthreaded core counts double their real value on every downstream consumer.
    """
    profile = parse_linux_probe(_CPUINFO_TWO_CORE_FOUR_THREAD, _MEMINFO, "")

    assert profile.cores == 2
    assert profile.threads == 4
    assert profile.cpu_name == "Test Linux CPU"


def test_linux_gpu_enumeration_reads_only_display_class_lspci_lines():
    """An audio device sharing the same PCI bridge as a GPU must not be mistaken for one — only
    VGA/3D/Display controller class lines are display adapters.
    """
    profile = parse_linux_probe(_CPUINFO_TWO_CORE_FOUR_THREAD, _MEMINFO, _LSPCI_ONE_GPU)

    assert len(profile.gpus) == 1
    assert "Audio" not in profile.gpus[0].name
    assert profile.gpus[0].vendor == "intel"


def test_linux_meminfo_kb_converts_to_gb():
    profile = parse_linux_probe(_CPUINFO_TWO_CORE_FOUR_THREAD, _MEMINFO, "")
    assert profile.ram_gb == 32


def test_missing_lspci_output_degrades_to_zero_gpus_not_a_crash():
    """`lspci` genuinely may not be installed on a minimal container/VM image. Zero detected
    GPUs is the honest, degraded answer (`docs/PRINCIPLES.md` §4.4) — never a failed profile.
    """
    profile = parse_linux_probe(_CPUINFO_TWO_CORE_FOUR_THREAD, _MEMINFO, "")
    assert profile.gpus == ()

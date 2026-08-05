"""`select_execution_provider()` — pure function, synthetic `GpuLike` stand-ins, no real
hardware needed (matching `services/setup/hardware/detect.py`'s own parser-tests-with-
synthetic-input discipline one layer below this)."""

from __future__ import annotations

from dataclasses import dataclass

from common.execution_provider import select_execution_provider


@dataclass(frozen=True)
class _Gpu:
    vendor: str
    compute_api: str
    discrete: bool = True
    vram_gb: float | None = None


def test_no_gpus_falls_back_to_cpu():
    assert select_execution_provider([]) == "cpu"


def test_unknown_vendor_falls_back_to_cpu():
    gpu = _Gpu(vendor="unknown", compute_api="unknown")
    assert select_execution_provider([gpu]) == "cpu"


def test_nvidia_selects_cuda():
    gpu = _Gpu(vendor="nvidia", compute_api="cuda", vram_gb=12.0)
    assert select_execution_provider([gpu]) == "cuda"


def test_intel_on_windows_selects_directml():
    gpu = _Gpu(vendor="intel", compute_api="sycl", vram_gb=12.0)
    assert select_execution_provider([gpu], os_name="Windows") == "directml"


def test_intel_on_linux_selects_openvino():
    gpu = _Gpu(vendor="intel", compute_api="sycl", vram_gb=12.0)
    assert select_execution_provider([gpu], os_name="Linux") == "openvino"


def test_amd_rocm_falls_back_to_cpu_not_a_removed_ep():
    """The classic ROCm EP was removed from ONNX Runtime as of 1.23, and MIGraphX (the
    current AMD path) has no Windows GPU path at all yet -- CPU is the honest answer,
    never a guessed EP name that likely isn't installed."""
    gpu = _Gpu(vendor="amd", compute_api="rocm", vram_gb=16.0)
    assert select_execution_provider([gpu]) == "cpu"


def test_prefers_discrete_over_integrated_regardless_of_vram():
    integrated = _Gpu(vendor="intel", compute_api="sycl", discrete=False, vram_gb=32.0)
    discrete = _Gpu(vendor="nvidia", compute_api="cuda", discrete=True, vram_gb=4.0)

    assert select_execution_provider([integrated, discrete]) == "cuda"


def test_among_discrete_gpus_prefers_more_vram():
    small = _Gpu(vendor="nvidia", compute_api="cuda", vram_gb=4.0)
    large = _Gpu(vendor="intel", compute_api="sycl", vram_gb=16.0)

    assert select_execution_provider([small, large], os_name="Windows") == "directml"


def test_gpu_with_no_reported_vram_is_not_preferred_over_one_that_reports_some():
    unknown_vram = _Gpu(vendor="nvidia", compute_api="cuda", vram_gb=None)
    known_vram = _Gpu(vendor="intel", compute_api="sycl", vram_gb=1.0)

    assert select_execution_provider([unknown_vram, known_vram], os_name="Windows") == "directml"


def test_real_gpuinfo_shape_satisfies_the_protocol_structurally():
    """The whole point of `GpuLike` being structural: `services.setup.contracts.GpuInfo`
    must work here with zero conversion, never imported by this module itself."""
    from services.setup.contracts import GpuInfo

    gpu = GpuInfo(name="Intel(R) Arc(TM) B580 Graphics", vendor="intel", discrete=True, vram_gb=12.0, compute_api="sycl")

    assert select_execution_provider([gpu], os_name="Windows") == "directml"

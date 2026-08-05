"""`select_execution_provider()` — pure function, synthetic `GpuLike` stand-ins, no real
hardware needed (matching `services/setup/hardware/detect.py`'s own parser-tests-with-
synthetic-input discipline one layer below this)."""

from __future__ import annotations

from dataclasses import dataclass

from common.execution_provider import EXECUTION_PROVIDERS, select_execution_provider


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


# --------------------------------------------------------------------- EXECUTION_PROVIDERS


def test_execution_providers_covers_the_full_deep_dive_8_1_vocabulary():
    devices = {ep.device for ep in EXECUTION_PROVIDERS}
    assert devices == {"cpu", "cuda", "tensorrt", "directml", "openvino", "qnn", "migraphx"}


def test_cpu_is_installable_despite_having_no_separate_pip_package():
    cpu = next(ep for ep in EXECUTION_PROVIDERS if ep.device == "cpu")
    assert cpu.pip_package is None
    assert cpu.installable is True


def test_cuda_and_directml_are_installable_with_real_pip_packages():
    by_device = {ep.device: ep for ep in EXECUTION_PROVIDERS}
    assert by_device["cuda"].installable is True
    assert by_device["cuda"].pip_package == "onnxruntime-genai-cuda"
    assert by_device["directml"].installable is True
    assert by_device["directml"].pip_package == "onnxruntime-genai-directml"


def test_tensorrt_is_installable_via_the_shared_cuda_package():
    """TensorRT genuinely installs via the same wheel CUDA does -- real and installable,
    just not its own *separate* pip package (confirmed live: no
    onnxruntime-genai-tensorrt wheel exists)."""
    tensorrt = next(ep for ep in EXECUTION_PROVIDERS if ep.device == "tensorrt")
    assert tensorrt.pip_package == "onnxruntime-genai-cuda"
    assert tensorrt.installable is True


def test_migraphx_is_honestly_not_installable():
    """No pip wheel and no NuGet package under the expected name was found on nuget.org
    when checked live -- the one real device in the catalog with no confirmed
    distribution channel at all."""
    migraphx = next(ep for ep in EXECUTION_PROVIDERS if ep.device == "migraphx")
    assert migraphx.pip_package is None
    assert migraphx.nuget_package is None
    assert migraphx.installable is False


def test_openvino_and_qnn_are_installable_via_nuget_not_pip():
    """No pip wheel installs either -- but a real NuGet-distributed EP plugin package
    exists for both (confirmed live: downloaded, extracted, and for OpenVINO specifically,
    successfully registered with a real `onnxruntime_genai.register_execution_provider_
    library()` call). `core/inference/ep_plugins.py` is the real download/register
    mechanism behind `nuget_package` below."""
    by_device = {ep.device: ep for ep in EXECUTION_PROVIDERS}
    for device, expected_package in (
        ("openvino", "Intel.ML.OnnxRuntime.EP.OpenVINO"),
        ("qnn", "Microsoft.ML.OnnxRuntime.QNN"),
    ):
        ep = by_device[device]
        assert ep.pip_package is None, device
        assert ep.nuget_package == expected_package, device
        assert ep.installable is True, device


def test_every_provider_has_a_real_confidence_tier():
    for ep in EXECUTION_PROVIDERS:
        assert ep.confidence in ("high", "medium", "low"), ep.device

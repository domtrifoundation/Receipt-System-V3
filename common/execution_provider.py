"""Shared execution-provider selection — `docs/apis/v3-deepdive-02-inference-api.md` §8.6's
own "the shared session/EP-selection utility... generic-enough plumbing to live outside
either domain [OCR or Inference]... building an ordered `providers=[...]` list from a
hardware profile plus a config'd preference is identical logic whether the caller is
RapidOCR or an ONNX GenAI model." This is that utility — designed once, never built until
now (confirmed live: nothing in this repo ever called anything like this before tonight).

**Structural typing on purpose, not a `services.setup.contracts.HardwareProfile` import.**
`docs/PRINCIPLES.md` §1.3 and this repo's own established convention (`core/inference/
contracts.py`'s own `BlobRef`, re-declared rather than imported from
`core.persistence.contracts`, "this package's own Protocol only ever needs `.logical_id`")
apply identically here: `common/` sits beneath every service, including Setup itself, so a
real import of `services.setup.contracts` would risk exactly the kind of cross-layer
dependency this project's package layout exists to prevent. `GpuLike` names only the four
attributes this module actually reads; `services.setup.contracts.GpuInfo` already satisfies
it structurally with zero conversion needed at any real call site.
"""

from __future__ import annotations

import platform
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "EXECUTION_PROVIDERS",
    "ExecutionProviderInfo",
    "GpuLike",
    "select_execution_provider",
]


@dataclass(frozen=True)
class ExecutionProviderInfo:
    """One entry in `EXECUTION_PROVIDERS` — the honest, real capability matrix behind
    manual EP selection (deep-dive §8.1's own per-provider confidence grading, made data
    instead of only prose). `pip_package` is `None` exactly when no prebuilt
    `onnxruntime-genai*` wheel installs this provider at all — confirmed live against the
    real PyPI index (`pip index versions onnxruntime-genai-tensorrt`/`-qnn`/`-rocm` all
    return "No matching distribution found"), not assumed from the deep-dive's own prose
    alone. A device with `pip_package=None` is still real, still selectable for
    *generation* (`config.append_provider(name)` doesn't require the venv to have been
    specially provisioned — it just fails at model-load time if the running interpreter's
    `onnxruntime-genai` build doesn't actually have that provider compiled in, the same
    "confidence varies, a real install failure specifically is not a surprise" honesty the
    deep-dive itself states) — provisioning just cannot swap the venv onto a wheel that
    doesn't exist, and says so.
    """

    device: str
    label: str
    confidence: str
    """`"high"` / `"medium"` / `"low"` — deep-dive §8.1's own per-provider grading,
    verbatim."""
    pip_package: str | None
    """The real `onnxruntime-genai*` package this device installs, or `None` when either
    no swap is needed (`"cpu"`, always already installed by the base requirements.txt) or
    no prebuilt wheel exists for it at all and `venv_provisioning.py` leaves the venv on
    whatever it already has rather than guessing at a package name — `installable` below
    is what actually distinguishes those two `None` cases."""
    note: str
    nuget_package: str | None = None
    """The real NuGet package id carrying this device's ONNX Runtime EP plugin DLL, or
    `None` when no such package exists. A genuinely separate distribution channel from
    `pip_package` — Windows ML's own `ExecutionProviderCatalog` publishes OpenVINO/QNN/
    MIGraphX/NvTensorRtRtx EP plugins this way, not as pip wheels, confirmed live
    (`core/inference/CLAUDE.md`'s "OpenVINO specifically re-checked..." account): a NuGet
    package is a plain downloadable zip (no MSIX/package-identity requirement, unlike
    `ExecutionProviderCatalog`'s own Python API, which threw `OSError: The process has no
    package identity` when called from this project's own unpackaged venv processes), and
    `onnxruntime_genai.register_execution_provider_library(provider_name, dll_path)`
    genuinely accepts a DLL extracted from one — live-confirmed for OpenVINO specifically
    (downloaded `Intel.ML.OnnxRuntime.EP.OpenVINO` 1.6.1, extracted
    `onnxruntime_providers_openvino_plugin.dll`, registered successfully under
    `"OpenVINOExecutionProvider"` — the same provider-name string `onnx_genai_backend.py`'s
    own `_PROVIDER_NAMES` already guessed). `core/inference/ep_plugins.py` is the real
    download/extract/register mechanism behind this field."""

    @property
    def installable(self) -> bool:
        """Real installability, not just "has its own separate pip package" — `"cpu"` has
        `pip_package=None` because it needs no swap (it's the base install every venv
        already gets), not because it is unavailable. Every other device's installability
        is whether a real prebuilt wheel OR a real NuGet-distributed EP plugin exists for
        it — two genuinely different, both real, distribution channels."""
        return self.device == "cpu" or self.pip_package is not None or self.nuget_package is not None


#: The full device vocabulary from the deep-dive's own §8.1, as real, checkable data —
#: not scattered across docstrings. Order matches the deep-dive's own listing.
EXECUTION_PROVIDERS: tuple[ExecutionProviderInfo, ...] = (
    ExecutionProviderInfo("cpu", "CPU", "high", None, "The universal default — always available."),
    ExecutionProviderInfo(
        "cuda", "CUDA (NVIDIA)", "high", "onnxruntime-genai-cuda",
        "CUDA 12.x is the practical minimum (deep-dive §8.1) — confirm driver compatibility.",
    ),
    ExecutionProviderInfo(
        "tensorrt", "TensorRT (NVIDIA)", "low", "onnxruntime-genai-cuda",
        "Rides on the same CUDA-enabled wheel, selected by provider name at runtime, not a "
        "separate package (confirmed live: no onnxruntime-genai-tensorrt wheel exists on "
        "PyPI). A fallback chain with CUDA, not a replacement for it (deep-dive §8.1) — "
        "engine caching is mandatory or every session pays a slow first-run rebuild.",
    ),
    ExecutionProviderInfo(
        "directml", "DirectML (Windows, most GPUs)", "high", "onnxruntime-genai-directml",
        "The broadly-compatible Windows path for any DirectX12 GPU, Intel/AMD/NVIDIA alike.",
    ),
    ExecutionProviderInfo(
        "openvino", "OpenVINO (Intel)", "low", None,
        "No prebuilt onnxruntime-genai *pip* wheel installs this (confirmed against the "
        "real PyPI index, and Microsoft's own official docs — onnxruntime.ai/docs/genai/"
        "howto/install lists only cpu/directml/cuda12/cuda11(source) pip variants; the "
        "official build-from-source page documents only --use_dml/--use_trt_rtx/--use_cuda). "
        "A real, separate, working path exists via NuGet instead — Windows ML's own "
        "ExecutionProviderCatalog publishes the OpenVINO EP plugin as a plain downloadable "
        "package (`nuget_package` below), and calling ExecutionProviderCatalog's own Python "
        "API directly fails with `OSError: The process has no package identity` (an MSIX "
        "requirement this project's unpackaged venv processes don't have) — but downloading "
        "the NuGet package directly and calling onnxruntime_genai.register_execution_"
        "provider_library() with its extracted DLL genuinely works, live-confirmed "
        "(`Intel.ML.OnnxRuntime.EP.OpenVINO` 1.6.1, provider name "
        "\"OpenVINOExecutionProvider\"). onnxruntime-genai-winml separately reports "
        "is_openvino_available()==True without any of this, but fails at actual model load "
        "with 'OpenVINO execution provider is not supported in this build' — that flag alone "
        "is not evidence of a working install. `core/inference/ep_plugins.py` is the real "
        "download/register mechanism; `venv_provisioning.py` pre-fetches the plugin during "
        "provisioning so no network call happens on the generation path.",
        nuget_package="Intel.ML.OnnxRuntime.EP.OpenVINO",
    ),
    ExecutionProviderInfo(
        "qnn", "QNN (Qualcomm NPU)", "medium", None,
        "Same real NuGet path as OpenVINO above (`Microsoft.ML.OnnxRuntime.QNN`, confirmed "
        "to exist and downloaded/inspected live) — no prebuilt onnxruntime-genai pip "
        "wheel, but a real EP plugin package exists. Two real, live-confirmed caveats "
        "OpenVINO doesn't share: (1) the package only ships a `runtimes/win-arm64/` "
        "native build — no x64 build exists at all, since Snapdragon's Hexagon NPU is "
        "ARM64-only hardware, so this is genuinely uninstallable (not just unverified) on "
        "any x64 Windows machine, this development machine included; (2) registration "
        "itself is NOT live-confirmed even on paper-compatible ARM64 hardware — stated "
        "honestly rather than assumed working by analogy to OpenVINO's own live-tested "
        "path. This project's own hardware detection also cannot see NPUs at all yet "
        "(services/setup/hardware/detect.py's own documented gap), so auto-selection "
        "never picks this regardless.",
        nuget_package="Microsoft.ML.OnnxRuntime.QNN",
    ),
    ExecutionProviderInfo(
        "migraphx", "MIGraphX (AMD)", "low", None,
        "The current AMD path (the classic ROCm EP was removed from ONNX Runtime as of "
        "1.23) — no official Windows GPU path exists yet at all (deep-dive §8.1); "
        "Linux/WSL2 has the working path. No prebuilt onnxruntime-genai pip wheel either "
        "way, and unlike OpenVINO/QNN above, no NuGet package exists either — checked live "
        "twice: both the exact expected package id and a real NuGet full-text search for "
        "\"MIGraphX\" (nuget.org's own search API, not just a guessed-name lookup) return "
        "zero results. Same real gap for TensorRT-RTX specifically (`tensorrt`'s own entry "
        "below installs via the shared CUDA wheel instead, a working, different path — see "
        "that entry): a NuGet search for \"NvTensorRtRtx\" also returns zero results. "
        "Windows ML's own documented catalog lists both as real, MSIX-distributed EPs "
        "(`learn.microsoft.com/windows/ai/new-windows-ml/supported-execution-providers`), "
        "so a real path likely exists through that mechanism specifically — but, per the "
        "openvino/qnn entries above, that whole mechanism requires MSIX package identity "
        "this project's unpackaged venv architecture doesn't have, and no NuGet escape "
        "hatch was found for either of these two the way there was for openvino/qnn.",
    ),
)


@runtime_checkable
class GpuLike(Protocol):
    """The whole shape this module needs from a detected GPU — `services.setup.contracts.
    GpuInfo` already has exactly these four attributes, so passing `HardwareProfile.gpus`
    directly here needs no conversion at any real call site."""

    vendor: str
    compute_api: str
    discrete: bool
    vram_gb: float | None


def select_execution_provider(gpus: Iterable[GpuLike], *, os_name: str | None = None) -> str:
    """Picks this project's own device vocabulary string (`"cpu"`/`"cuda"`/`"directml"`/
    `"openvino"`) from a real, detected GPU list — never guessed, matching
    `services/setup/hardware/detect.py`'s own "never guess a number" discipline one level
    up. Falls back to `"cpu"` for no GPU, an unclassifiable vendor, or a compute API this
    project doesn't yet have a working EP path for (AMD/ROCm today — see below).

    Picks the best *discrete* GPU by VRAM when more than one exists (an integrated GPU is
    never preferred over a discrete one, matching `detect.py`'s own discrete-classification
    intent); among GPUs of equal discreteness, the one with more VRAM wins.

    `os_name` defaults to the real `platform.system()` — overridable so this stays a pure,
    synchronous, unit-testable function with no live-hardware dependency in its own tests,
    the same posture `detect.py`'s own `parse_windows_probe`/`parse_linux_probe` establish
    for hardware parsing one level below this.
    """
    resolved_os = os_name if os_name is not None else platform.system()

    best: GpuLike | None = None
    for gpu in gpus:
        if best is None:
            best = gpu
            continue
        if (gpu.discrete, gpu.vram_gb or 0) > (best.discrete, best.vram_gb or 0):
            best = gpu

    if best is None:
        return "cpu"

    if best.compute_api == "cuda":
        return "cuda"

    if best.compute_api == "sycl":
        # Intel's real EP split (deep-dive §8.1): DirectML is the broadly-compatible
        # Windows path; OpenVINO is Intel's own, actively-developed path elsewhere.
        return "directml" if resolved_os == "Windows" else "openvino"

    if best.compute_api == "rocm":
        # Real, deliberate, not an oversight: the classic ROCm execution provider was
        # removed from ONNX Runtime as of the 1.23 release, and MIGraphX (the current AMD
        # path) has no official Windows GPU path at all yet (deep-dive §8.1, corrected
        # from an earlier version of the OCR deep-dive that listed both as live options).
        # Attempting either EP here would be exactly the "assume acceleration from an EP's
        # mere presence" mistake §8.5 warns against — CPU is the honest current answer.
        return "cpu"

    return "cpu"

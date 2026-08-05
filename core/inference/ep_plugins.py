"""Real NuGet-distributed execution-provider plugin acquisition and registration —
closing the gap `common/execution_provider.py`'s own `nuget_package` field documents.

**Why this exists, stated precisely.** No prebuilt `onnxruntime-genai` pip wheel installs
OpenVINO or QNN support (confirmed against the real PyPI index and Microsoft's own
official docs — see `core/inference/CLAUDE.md`'s "OpenVINO specifically re-checked..."
account). Windows ML's own `ExecutionProviderCatalog` *does* publish real EP plugin
packages for both, but its own Python API requires MSIX package identity
(`OSError: The process has no package identity`, confirmed live calling it from a plain
`python.exe` process) — a requirement this project's whole unpackaged-venv-per-service
architecture (`docs/PROCESS_TOPOLOGY.md`) does not meet and has no reason to adopt just
for this. The actual official distribution mechanism *underneath* that catalog is plain
NuGet — a NuGet package is nothing more than a downloadable zip, no MSIX involved — and
`onnxruntime_genai.register_execution_provider_library(provider_name, dll_path)` genuinely
accepts a DLL extracted from one. Live-confirmed for OpenVINO specifically: downloaded
`Intel.ML.OnnxRuntime.EP.OpenVINO` 1.6.1 for real, extracted
`onnxruntime_providers_openvino_plugin.dll`, called `register_execution_provider_library`
against it, and it succeeded.

**Deliberately two separate steps, matching `model_provisioning.py`'s own "provisioning
happens once, generation never touches the network" split.** `ensure_ep_plugin()` is the
real network-touching step — reuses Phase A's resumable `download_file()`, called from
`venv_provisioning.py` during install/update, never from the generation path.
`register_ep_plugin()` is the real, synchronous, no-network step — called from
`onnx_genai_backend.py`'s own `load()` right before `og.Config`/`config.append_provider()`,
idempotent against `onnxruntime_genai`'s own real "already registered" error (confirmed
live: calling `register_execution_provider_library` twice for the same provider name
raises `RuntimeError: library is already registered under <name>` — a real native-layer
constraint, not a defensive assumption).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from common.frozen_dict import FrozenDict
from services.update.proving_grounds.contracts import DownloadResult
from services.update.proving_grounds.download import download_file

__all__ = [
    "EP_PLUGIN_SPECS",
    "EpPluginSpec",
    "ensure_ep_plugin",
    "ep_plugins_dir",
    "plugin_dll_path",
    "register_ep_plugin",
]

_NUGET_DOWNLOAD_URL = "https://www.nuget.org/api/v2/package/{package_id}/{version}"


@dataclass(frozen=True)
class EpPluginSpec:
    """One device's real NuGet-distributed EP plugin — device vocabulary, package
    coordinates, the provider name `onnxruntime_genai` itself expects, and the DLL's
    real path inside the extracted package (both confirmed live for OpenVINO; QNN's
    package/path are real per the NuGet index but not live-loaded — no Qualcomm hardware
    on the development machine that confirmed OpenVINO, stated honestly rather than
    assumed working by analogy)."""

    device: str
    nuget_package_id: str
    nuget_version: str
    provider_name: str
    """The string `onnxruntime_genai.register_execution_provider_library()`/
    `config.append_provider()` expect — matches `onnx_genai_backend.py`'s own
    `_PROVIDER_NAMES` entry for this device, confirmed live for OpenVINO."""
    dll_relpath: str
    """Path to the plugin DLL inside the extracted NuGet package, forward-slash
    separated regardless of host OS (matches the real zip's own internal paths). Real,
    inspected live for both entries below — QNN's own package ships only a
    `runtimes/win-arm64/` native build (Snapdragon's Hexagon NPU is ARM64-only hardware,
    confirmed by listing the extracted package's own `runtimes/` directory: no `win-x64`
    sibling exists at all), so `ensure_ep_plugin("qnn", ...)` genuinely cannot succeed on
    an x64 host — `common/execution_provider.py`'s own `qnn` entry states this plainly."""


#: Real coordinates, not guessed — `nuget_version` pinned to the exact version live-tested
#: (OpenVINO) or the newest confirmed-existing version at research time (QNN), never
#: "latest" — an unpinned version would make this module's own behavior depend on
#: whatever NuGet happens to serve on a given day, the same "never guess a number"
#: discipline `services/setup/hardware/detect.py` already holds itself to.
EP_PLUGIN_SPECS: FrozenDict[str, EpPluginSpec] = FrozenDict(
    {
        "openvino": EpPluginSpec(
            device="openvino",
            nuget_package_id="Intel.ML.OnnxRuntime.EP.OpenVINO",
            nuget_version="1.6.1",
            provider_name="OpenVINOExecutionProvider",
            dll_relpath="runtimes/win-x64/native/onnxruntime_providers_openvino_plugin.dll",
        ),
        "qnn": EpPluginSpec(
            device="qnn",
            nuget_package_id="Microsoft.ML.OnnxRuntime.QNN",
            nuget_version="1.24.0",
            provider_name="QNNExecutionProvider",
            dll_relpath="runtimes/win-arm64/native/onnxruntime_providers_qnn.dll",
        ),
    }
)

#: In-process registration cache — `onnxruntime_genai.register_execution_provider_library`
#: raises on a genuine second call for the same provider name (confirmed live), and
#: `get_worker()` (`model_registry.py`) can load more than one preset onto the same
#: device within one Inference process, so `register_ep_plugin` must be safe to call
#: repeatedly within a process even though the native layer itself is not.
_registered_providers: set[str] = set()


def ep_plugins_dir(install_root: Path) -> Path:
    """Where downloaded EP plugin packages live — a sibling of `models`/`config`/`data`
    under the real per-install top-level directory (`docs/PRINCIPLES.md` §1.6), never
    inside this repo clone itself."""
    return install_root / "ep_plugins"


def plugin_dll_path(device: str, install_root: Path) -> Path | None:
    """The real, expected on-disk path for `device`'s plugin DLL once provisioned —
    a pure path computation, no filesystem access. `None` for a device with no real
    NuGet-distributed plugin (`EP_PLUGIN_SPECS` doesn't cover it)."""
    spec = EP_PLUGIN_SPECS.get(device)
    if spec is None:
        return None
    return ep_plugins_dir(install_root) / device / Path(spec.dll_relpath)


async def ensure_ep_plugin(
    device: str, install_root: Path, *, download_url_template: str = _NUGET_DOWNLOAD_URL
) -> DownloadResult:
    """Downloads and extracts `device`'s real NuGet EP plugin package if not already
    present — the one real network-touching step in this module, called during
    provisioning (`venv_provisioning.py`), never during generation.

    Idempotent: if the expected DLL is already on disk, this is a no-op that reports a
    real, honest zero-byte success rather than re-downloading a multi-hundred-megabyte
    package on every provisioning re-run (`docs/apis/v3-deepdive-11-setup-api.md` §4's own
    re-runnability property, the identical posture `venv_provisioning.provision_service`
    already holds for an existing venv).

    `download_url_template`, overridable for tests exactly like `model_provisioning.py`'s
    own `hub_lister` seam — real code always uses the real NuGet endpoint; a test points
    this at a real local HTTP server serving a real, minimal zip instead of downloading a
    genuine multi-hundred-megabyte package on every run.
    """
    spec = EP_PLUGIN_SPECS.get(device)
    if spec is None:
        return DownloadResult(
            ok=False, error_code="NO_EP_PLUGIN", error_detail=f"no known NuGet EP plugin for device {device!r}"
        )

    dll_path = plugin_dll_path(device, install_root)
    if dll_path is not None and dll_path.exists():
        return DownloadResult(ok=True, destination=str(dll_path), bytes_written=0, resumed=False)

    target_dir = ep_plugins_dir(install_root) / device
    nupkg_path = ep_plugins_dir(install_root) / f"{device}.nupkg"
    url = download_url_template.format(package_id=spec.nuget_package_id, version=spec.nuget_version)

    result = await download_file(url, nupkg_path)
    if not result.ok:
        return result

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(nupkg_path) as archive:
            archive.extractall(target_dir)
    except (zipfile.BadZipFile, OSError) as exc:
        return DownloadResult(
            ok=False, error_code="EXTRACT_FAILED", error_detail=f"{type(exc).__name__}: {exc}"
        )

    extracted_dll = target_dir / Path(spec.dll_relpath)
    if not extracted_dll.exists():
        return DownloadResult(
            ok=False,
            error_code="PLUGIN_DLL_MISSING",
            error_detail=f"{spec.dll_relpath} not found in extracted {spec.nuget_package_id} {spec.nuget_version}",
        )

    return DownloadResult(ok=True, destination=str(extracted_dll), bytes_written=result.bytes_written)


def register_ep_plugin(device: str, install_root: Path) -> bool:
    """Registers `device`'s already-provisioned plugin DLL with `onnxruntime_genai` —
    real, synchronous, no network access. Returns `False` (never raises) whenever
    registration cannot happen: no known plugin for this device, the plugin was never
    provisioned (`ensure_ep_plugin` wasn't run, or failed), or `onnxruntime_genai` isn't
    installed in this interpreter — every case degrades to "the caller falls back to
    whatever `og.Config`'s own default behavior is for an unregistered provider name"
    rather than raising into a model load (`docs/PRINCIPLES.md` §4.4).

    Idempotent within a process via `_registered_providers` — `onnxruntime_genai`'s own
    `register_execution_provider_library` raises `RuntimeError` on a genuine second call
    for the same provider name (confirmed live), which would otherwise fail a second
    preset's load onto the same device.
    """
    spec = EP_PLUGIN_SPECS.get(device)
    if spec is None:
        return False
    if spec.provider_name in _registered_providers:
        return True

    dll_path = plugin_dll_path(device, install_root)
    if dll_path is None or not dll_path.exists():
        return False

    try:
        import onnxruntime_genai as og  # noqa: PLC0415
    except ImportError:
        return False

    try:
        og.register_execution_provider_library(spec.provider_name, str(dll_path))
    except Exception:  # noqa: BLE001 - a registration failure degrades to "not registered"
        return False

    _registered_providers.add(spec.provider_name)
    return True

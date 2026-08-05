"""`core.inference`'s own real, live-found gap: `requirements.txt`'s own comment claims
"exactly one of these three [onnxruntime-genai variants] gets installed per machine,
chosen from Setup API's shared hardware detection... never guessed" -- nothing ever backed
that claim before this pass. Real pip subprocess calls are mocked here (unlike this
folder's own `test_venv_provisioning.py`, which deliberately uses real venvs/pip for the
provisioning mechanics themselves) because what's under test is *which* packages this
module chooses to install/uninstall and in what order, not pip's own real behavior --
`test_download_resume.py`-style real-network coverage exists separately in this repo for
the download side of provisioning, not the pip side.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.setup.contracts import ProvisionErrorCode, ServiceVenvSpec
from services.setup.venv_provisioning import BASE_REQUIREMENTS_RELPATH, provision_service


def _clone_with_inference(tmp_path: Path) -> Path:
    root = tmp_path / "x02.01.03_a1b2c3d"
    base_path = root / BASE_REQUIREMENTS_RELPATH
    base_path.parent.mkdir(parents=True, exist_ok=True)
    base_path.write_text("", encoding="utf-8")

    pkg = root / "core" / "inference"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "requirements.txt").write_text("onnxruntime-genai>=0.6\n", encoding="utf-8")
    return root


def _ok(*_args, **_kwargs) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail(detail: str):
    def _runner(*_args, **_kwargs) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=detail)

    return _runner


@pytest.fixture
def spec(tmp_path: Path) -> ServiceVenvSpec:
    root = _clone_with_inference(tmp_path)
    return ServiceVenvSpec(
        import_path="core.inference",
        source_dir=root / "core" / "inference",
        venv_dir=root / ".venvs" / "core.inference",
        requirement_files=(root / "core" / "inference" / "requirements.txt",),
    )


def _real_or_fake_venv_setup(monkeypatch, tmp_path: Path, spec: ServiceVenvSpec):
    """Fakes venv creation/interpreter-existence so `provision_service` reaches the
    dependency-install step without a real `python -m venv` call — the EP-swap logic is
    what's under test, not venv creation itself (already covered elsewhere)."""
    import services.setup.venv_provisioning as vp

    spec.venv_dir.mkdir(parents=True, exist_ok=True)
    fake_python = spec.venv_dir / ("Scripts" if __import__("os").name == "nt" else "bin")
    fake_python.mkdir(parents=True, exist_ok=True)
    interpreter = fake_python / ("python.exe" if __import__("os").name == "nt" else "python")
    interpreter.write_text("", encoding="utf-8")
    monkeypatch.setattr(vp, "venv_python", lambda venv_dir: interpreter)


def test_cpu_device_never_touches_onnxruntime_genai_at_all(monkeypatch, spec, tmp_path):
    import services.setup.venv_provisioning as vp

    _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)
    calls = []

    def _tracking_run(cmd):
        calls.append(cmd)
        return _ok()

    monkeypatch.setattr(vp, "_run_with_retries", _tracking_run)

    outcome = provision_service(spec, inference_device="cpu", upgrade=True)

    assert outcome.error is None
    assert not any("uninstall" in c for c in calls)
    assert not any("onnxruntime-genai-directml" in c or "onnxruntime-genai-cuda" in c for c in calls)


def test_directml_device_swaps_the_bare_package_for_the_directml_variant(monkeypatch, spec, tmp_path):
    import services.setup.venv_provisioning as vp

    _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)
    calls = []

    def _tracking_run(cmd):
        calls.append(cmd)
        return _ok()

    monkeypatch.setattr(vp, "_run_with_retries", _tracking_run)

    outcome = provision_service(spec, inference_device="directml", upgrade=True)

    assert outcome.error is None
    uninstall_calls = [c for c in calls if "uninstall" in c]
    install_calls = [c for c in calls if "install" in c and "uninstall" not in c]
    assert any("onnxruntime-genai" in c for c in uninstall_calls)
    assert any("onnxruntime-genai-directml" in c for c in install_calls)
    # The uninstall must happen before the variant install, never after.
    uninstall_index = calls.index(uninstall_calls[0])
    variant_install_index = next(i for i, c in enumerate(calls) if "onnxruntime-genai-directml" in c)
    assert uninstall_index < variant_install_index


def test_cuda_device_installs_the_cuda_variant(monkeypatch, spec, tmp_path):
    import services.setup.venv_provisioning as vp

    _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)
    calls = []
    monkeypatch.setattr(vp, "_run_with_retries", lambda cmd: (calls.append(cmd), _ok())[1])

    outcome = provision_service(spec, inference_device="cuda", upgrade=True)

    assert outcome.error is None
    assert any("onnxruntime-genai-cuda" in c for c in calls)


def test_tensorrt_device_installs_the_cuda_variant_not_a_fabricated_tensorrt_package(monkeypatch, spec, tmp_path):
    """Confirmed live against the real PyPI index: no `onnxruntime-genai-tensorrt`
    package exists. TensorRT rides on the CUDA-enabled build, selected by provider name
    at runtime -- installing anything else for `"tensorrt"` would be guessing at a
    package name that doesn't exist."""
    import services.setup.venv_provisioning as vp

    _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)
    calls = []
    monkeypatch.setattr(vp, "_run_with_retries", lambda cmd: (calls.append(cmd), _ok())[1])

    outcome = provision_service(spec, inference_device="tensorrt", upgrade=True)

    assert outcome.error is None
    assert any("onnxruntime-genai-cuda" in c for c in calls)
    assert not any("onnxruntime-genai-tensorrt" in c for c in calls)


def test_openvino_qnn_migraphx_have_no_installable_wheel_and_leave_the_venv_alone(monkeypatch, spec, tmp_path):
    """Real, honest gap (confirmed live against PyPI, not assumed): none of these three
    have a prebuilt onnxruntime-genai wheel, so provisioning must never guess at a
    package name for them -- the venv stays on the base CPU install."""
    import services.setup.venv_provisioning as vp

    for device in ("openvino", "qnn", "migraphx"):
        _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)
        calls = []
        monkeypatch.setattr(vp, "_run_with_retries", lambda cmd: (calls.append(cmd), _ok())[1])

        outcome = provision_service(spec, inference_device=device, upgrade=True)

        assert outcome.error is None, device
        assert not any("uninstall" in c for c in calls), device


def test_swap_failure_is_reported_as_data_not_a_silent_stay_on_cpu(monkeypatch, spec, tmp_path):
    """A failed swap must be visible to the caller, not silently leave the venv on
    whatever it happened to have -- `docs/PRINCIPLES.md` §4.1."""
    import services.setup.venv_provisioning as vp

    _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)

    def _run(cmd):
        if "install" in cmd and "uninstall" not in cmd and any("requirements.txt" in c for c in cmd):
            return _ok()  # the base requirements.txt install still succeeds
        if "uninstall" in cmd:
            return _ok()
        return _fail("simulated pip failure")(cmd)

    monkeypatch.setattr(vp, "_run_with_retries", _run)

    outcome = provision_service(spec, inference_device="directml", upgrade=True)

    assert outcome.error is not None
    assert outcome.error.code == ProvisionErrorCode.DEPENDENCY_INSTALL_FAILED
    assert "onnxruntime-genai-directml" in outcome.error.detail


def test_uninstall_failure_stops_before_attempting_the_variant_install(monkeypatch, spec, tmp_path):
    import services.setup.venv_provisioning as vp

    _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)
    calls = []

    def _run(cmd):
        calls.append(cmd)
        if "uninstall" in cmd:
            return _fail("uninstall exploded")(cmd)
        return _ok()

    monkeypatch.setattr(vp, "_run_with_retries", _run)

    outcome = provision_service(spec, inference_device="directml", upgrade=True)

    assert outcome.error is not None
    assert not any("onnxruntime-genai-directml" in c for c in calls if "uninstall" not in c and c != calls[-1])
    # No install of the variant package was ever attempted after the uninstall failed.
    assert not any(
        "install" in c and "uninstall" not in c and "onnxruntime-genai-directml" in c for c in calls
    )


def test_a_device_with_no_known_variant_package_leaves_the_venv_alone(monkeypatch, spec, tmp_path):
    """A device string this module has no variant mapping for (anything other than
    `"cuda"`/`"directml"` -- `"cpu"`, `"openvino"`, an unrecognized value) is left as the
    base CPU install rather than guessing at a package name that may not exist."""
    import services.setup.venv_provisioning as vp

    _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)
    calls = []
    monkeypatch.setattr(vp, "_run_with_retries", lambda cmd: (calls.append(cmd), _ok())[1])

    outcome = provision_service(spec, inference_device="openvino", upgrade=True)

    assert outcome.error is None
    assert not any("uninstall" in c for c in calls)


def test_openvino_with_install_root_fetches_the_real_nuget_ep_plugin(monkeypatch, spec, tmp_path):
    """The other real distribution channel `EXECUTION_PROVIDERS` documents (`nuget_
    package`, `core/inference/ep_plugins.py`) -- exercised here via `ensure_ep_plugin`
    itself patched (real network coverage lives in `test_ep_plugins.py`'s own local-HTTP-
    server tests), proving `provision_service` reaches and calls it correctly with a real
    `install_root`."""
    import services.setup.venv_provisioning as vp
    from services.update.proving_grounds.contracts import DownloadResult

    _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)
    monkeypatch.setattr(vp, "_run_with_retries", lambda cmd: _ok())

    calls = []

    async def _fake_ensure(device, install_root):
        calls.append((device, install_root))
        return DownloadResult(ok=True, destination="fake.dll", bytes_written=123)

    import core.inference.ep_plugins as ep_plugins_module

    monkeypatch.setattr(ep_plugins_module, "ensure_ep_plugin", _fake_ensure)

    install_root = tmp_path / "install"
    outcome = provision_service(spec, inference_device="openvino", upgrade=True, install_root=install_root)

    assert outcome.error is None
    assert calls == [("openvino", install_root)]


def test_openvino_ep_plugin_fetch_failure_is_reported_as_data(monkeypatch, spec, tmp_path):
    import services.setup.venv_provisioning as vp
    from services.update.proving_grounds.contracts import DownloadResult

    _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)
    monkeypatch.setattr(vp, "_run_with_retries", lambda cmd: _ok())

    async def _fake_ensure(device, install_root):
        return DownloadResult(ok=False, error_code="DOWNLOAD_FAILED", error_detail="simulated network failure")

    import core.inference.ep_plugins as ep_plugins_module

    monkeypatch.setattr(ep_plugins_module, "ensure_ep_plugin", _fake_ensure)

    outcome = provision_service(
        spec, inference_device="openvino", upgrade=True, install_root=tmp_path / "install"
    )

    assert outcome.error is not None
    assert outcome.error.code == ProvisionErrorCode.DEPENDENCY_INSTALL_FAILED
    assert "simulated network failure" in outcome.error.detail


def test_migraphx_with_install_root_still_leaves_the_venv_alone(monkeypatch, spec, tmp_path):
    """migraphx has neither a pip wheel nor a confirmed NuGet package -- `install_root`
    being given must not change that; there is nothing real to fetch."""
    import services.setup.venv_provisioning as vp

    _real_or_fake_venv_setup(monkeypatch, tmp_path, spec)
    calls = []
    monkeypatch.setattr(vp, "_run_with_retries", lambda cmd: (calls.append(cmd), _ok())[1])

    outcome = provision_service(
        spec, inference_device="migraphx", upgrade=True, install_root=tmp_path / "install"
    )

    assert outcome.error is None
    assert not any("uninstall" in c for c in calls)


def test_other_services_are_never_affected_by_inference_device(monkeypatch, tmp_path):
    """`inference_device` must only ever change `core.inference`'s own venv, checked by
    import path -- not applied globally to whatever service happens to be provisioned."""
    import services.setup.venv_provisioning as vp

    root = tmp_path / "x02.01.03_a1b2c3d"
    base_path = root / BASE_REQUIREMENTS_RELPATH
    base_path.parent.mkdir(parents=True, exist_ok=True)
    base_path.write_text("", encoding="utf-8")
    pkg = root / "core" / "ocr"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    other_spec = ServiceVenvSpec(
        import_path="core.ocr", source_dir=pkg, venv_dir=root / ".venvs" / "core.ocr",
        requirement_files=(),
    )
    _real_or_fake_venv_setup(monkeypatch, tmp_path, other_spec)
    calls = []
    monkeypatch.setattr(vp, "_run_with_retries", lambda cmd: (calls.append(cmd), _ok())[1])

    outcome = provision_service(other_spec, inference_device="directml", upgrade=True)

    assert outcome.error is None
    assert calls == []  # no requirement files, and definitely no onnxruntime-genai swap

"""Per-service venv provisioning — the mechanism behind `docs/VENV_AND_IMPORTS.md`.

`docs/PROCESS_TOPOLOGY.md` §1/§2/§7 asserts that every Core API owns its own venv, and
`v3-deepdive-38-supervisor.md` §2 says Supervisor launches each service from that venv — but no
document ever said who *creates* them. This module is that missing step.

**Shared plumbing with two callers**, exactly like `dev_mode_strip.strip_development_content()`
(`docs/PRINCIPLES.md` §1.5): Setup API provisions the first clone's venvs in its finalize
routine (`v3-deepdive-11-setup-api.md` §7.4), and Update API's `release_manager.py` provisions
every subsequent clone's, since every update is a fresh clone and a fresh clone has no
`.venvs/` yet. One implementation, because two copies drift.

**What a venv here does and does not contain.** Third-party packages only. First-party code
(`common/`, `core/*`, `services/*`) is never installed — it resolves from the clone root on
`PYTHONPATH` at launch. See `docs/VENV_AND_IMPORTS.md` §3 for why that beats `pip install -e .`
(N clones × 32 editable installs whose failure mode is importing *another clone's* code) and why
it beats relying on `cwd` (a `spawn`-start-method child re-derives `sys.path` from the
environment, and three APIs in this system fork their own workers).

Errors are data (`docs/PRINCIPLES.md` §4.1). Nothing here raises on a failed service: one bad
venv is reported against that service and provisioning continues, because an operator deciding
whether a clone is salvageable needs the whole picture, not the first failure.
"""

from __future__ import annotations

import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path

from .contracts import (
    ProvisionError,
    ProvisionErrorCode,
    ProvisionOutcome,
    ProvisionReport,
    ServiceVenvSpec,
)

__all__ = [
    "BASE_REQUIREMENTS_RELPATH",
    "SERVICE_TREES",
    "VENVS_DIRNAME",
    "discover_services",
    "provision_clone",
    "provision_service",
    "venv_python",
]

#: The two trees that hold launchable services. Not a hardcoded list of the 32 APIs — see
#: `ServiceVenvSpec.import_path`'s own note on why enumeration-by-hand is the mistake this
#: project keeps re-making.
SERVICE_TREES = ("core", "services")

#: The shared runtime base every service venv gets before its own requirements
#: (`docs/VENV_AND_IMPORTS.md` §4). Rooted at `common/` rather than the repo root deliberately:
#: `common/` is the one package every service imports, so its dependency footprint is exactly
#: the set every service genuinely needs.
BASE_REQUIREMENTS_RELPATH = Path("common") / "requirements.txt"

#: Generated, never committed — a build product of the clone, like the webapp bundle
#: `build_webapp()` produces in the same finalize routine.
VENVS_DIRNAME = ".venvs"

_SERVICE_REQUIREMENTS_FILENAME = "requirements.txt"

#: Real, live-found gap closed here: `core/inference/requirements.txt`'s own comment
#: claims "exactly one of these three [onnxruntime-genai variants] gets installed per
#: machine, chosen from Setup API's shared hardware detection... never guessed" -- no code
#: anywhere ever backed that claim; every real install always got the bare CPU package.
#: `_BARE_ONNXRUNTIME_GENAI_PACKAGE` is what `core/inference/requirements.txt` already
#: pins; the base install always happens first (this dict is never consulted for `"cpu"`),
#: and this is the swap performed afterward only when a real non-CPU device was resolved.
_INFERENCE_IMPORT_PATH = "core.inference"
_BARE_ONNXRUNTIME_GENAI_PACKAGE = "onnxruntime-genai"
_ONNXRUNTIME_GENAI_VARIANT_BY_DEVICE = {
    "cuda": "onnxruntime-genai-cuda",
    "directml": "onnxruntime-genai-directml",
}


def venv_python(venv_dir: Path) -> Path:
    """The interpreter inside a provisioned venv.

    Windows puts it in `Scripts/python.exe`, POSIX in `bin/python`. Branching on `os.name`
    rather than `sys.platform` because that is the distinction that actually governs venv
    layout — `sys.platform` splits `linux` from `darwin`, which share the same answer here.
    """
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def discover_services(clone_root: Path) -> tuple[ServiceVenvSpec, ...]:
    """Every launchable service in a clone, resolved to a full venv spec.

    A service is a package directory (one containing `__init__.py`) directly under `core/` or
    `services/`. Discovery deliberately does not care whether that package is *implemented* —
    several are still 0-byte scaffolding, and a scaffolded package still gets a base-only venv
    rather than being silently skipped. Skipping would make the inventory lie about what the
    clone contains, and the honest inventory is the thing this project has repeatedly needed.
    """
    base_requirements = clone_root / BASE_REQUIREMENTS_RELPATH
    specs: list[ServiceVenvSpec] = []

    for tree in SERVICE_TREES:
        tree_dir = clone_root / tree
        if not tree_dir.is_dir():
            continue
        for source_dir in sorted(p for p in tree_dir.iterdir() if p.is_dir()):
            if source_dir.name.startswith((".", "__")):
                continue
            if not (source_dir / "__init__.py").exists():
                continue

            requirement_files: list[Path] = []
            if base_requirements.is_file():
                requirement_files.append(base_requirements)
            own = source_dir / _SERVICE_REQUIREMENTS_FILENAME
            if own.is_file():
                requirement_files.append(own)

            import_path = f"{tree}.{source_dir.name}"
            specs.append(
                ServiceVenvSpec(
                    import_path=import_path,
                    source_dir=source_dir,
                    venv_dir=clone_root / VENVS_DIRNAME / import_path,
                    requirement_files=tuple(requirement_files),
                )
            )

    return tuple(specs)


def provision_service(
    spec: ServiceVenvSpec,
    *,
    python_bin: str | None = None,
    upgrade: bool = False,
    inference_device: str = "cpu",
) -> ProvisionOutcome:
    """Create and populate one service's venv.

    Idempotent: an existing venv is left alone and reported with `created=False` unless
    `upgrade=True`, in which case its requirements are reinstalled into the existing
    environment. Re-running after a partial failure is a normal, safe operation
    (`v3-deepdive-11-setup-api.md` §4's re-runnability property).

    `inference_device` only ever affects `core.inference`'s own venv (§8.6 execution-
    provider selection) — every other service's provisioning is completely unaffected by
    this parameter, checked by import path, not applied globally.
    """
    interpreter = python_bin or sys.executable

    if not spec.source_dir.is_dir():
        return ProvisionOutcome(
            import_path=spec.import_path,
            venv_dir=spec.venv_dir,
            created=False,
            error=ProvisionError(
                code=ProvisionErrorCode.SOURCE_DIR_MISSING,
                detail=f"{spec.source_dir} is not a directory",
            ),
        )

    already_present = venv_python(spec.venv_dir).exists()
    created = False

    if not already_present:
        result = _run([interpreter, "-m", "venv", str(spec.venv_dir)])
        if result.returncode != 0:
            return ProvisionOutcome(
                import_path=spec.import_path,
                venv_dir=spec.venv_dir,
                created=False,
                error=ProvisionError(
                    code=ProvisionErrorCode.VENV_CREATION_FAILED,
                    detail=_stderr_of(result),
                ),
            )
        created = True
    elif not upgrade:
        return ProvisionOutcome(
            import_path=spec.import_path, venv_dir=spec.venv_dir, created=False
        )

    py = venv_python(spec.venv_dir)
    if not py.exists():
        return ProvisionOutcome(
            import_path=spec.import_path,
            venv_dir=spec.venv_dir,
            created=created,
            error=ProvisionError(
                code=ProvisionErrorCode.INTERPRETER_UNUSABLE,
                detail=f"venv reported success but {py} does not exist",
            ),
        )

    for req in spec.requirement_files:
        result = _run_with_retries([str(py), "-m", "pip", "install", "-r", str(req)])
        if result.returncode != 0:
            return ProvisionOutcome(
                import_path=spec.import_path,
                venv_dir=spec.venv_dir,
                created=created,
                error=ProvisionError(
                    code=ProvisionErrorCode.DEPENDENCY_INSTALL_FAILED,
                    detail=f"installing {req.name} for {spec.import_path}: {_stderr_of(result)}",
                ),
            )

    if spec.import_path == _INFERENCE_IMPORT_PATH:
        variant_package = _ONNXRUNTIME_GENAI_VARIANT_BY_DEVICE.get(inference_device)
        if variant_package is not None:
            swap_result = _swap_onnxruntime_genai_variant(py, variant_package)
            if swap_result is not None:
                return ProvisionOutcome(
                    import_path=spec.import_path, venv_dir=spec.venv_dir, created=created,
                    error=swap_result,
                )

    return ProvisionOutcome(
        import_path=spec.import_path, venv_dir=spec.venv_dir, created=created
    )


def _swap_onnxruntime_genai_variant(py: Path, variant_package: str) -> ProvisionError | None:
    """Replaces the bare CPU `onnxruntime-genai` (already installed by `core.inference`'s
    own `requirements.txt`, the base install every install gets regardless of hardware)
    with the hardware-matched variant — real, not a documented aspiration:
    `onnxruntime-genai`/`onnxruntime-genai-directml`/`onnxruntime-genai-cuda` each bundle a
    genuinely different native runtime and cannot coexist in one venv (confirmed live
    while building this: installing the DirectML variant into a venv that already has the
    CPU one requires the CPU one gone first, or pip's own dependency resolution leaves a
    broken mix). Uninstall failure degrades to a real, reported error rather than silently
    leaving the venv on the CPU-only package it started with — installing the swap without
    confirming the old one is gone risks exactly the broken-mix state just described.
    """
    uninstall = _run_with_retries([str(py), "-m", "pip", "uninstall", "-y", _BARE_ONNXRUNTIME_GENAI_PACKAGE])
    if uninstall.returncode != 0:
        return ProvisionError(
            code=ProvisionErrorCode.DEPENDENCY_INSTALL_FAILED,
            detail=f"removing {_BARE_ONNXRUNTIME_GENAI_PACKAGE} before installing {variant_package}: {_stderr_of(uninstall)}",
        )

    install = _run_with_retries([str(py), "-m", "pip", "install", variant_package])
    if install.returncode != 0:
        return ProvisionError(
            code=ProvisionErrorCode.DEPENDENCY_INSTALL_FAILED,
            detail=f"installing {variant_package}: {_stderr_of(install)}",
        )

    return None


def provision_clone(
    clone_root: Path,
    *,
    python_bin: str | None = None,
    upgrade: bool = False,
    max_workers: int | None = None,
    inference_device: str = "cpu",
) -> ProvisionReport:
    """Provision every service venv in a clone.

    Runs services concurrently: each one is a `pip` subprocess, so the work is genuinely I/O and
    process bound and threads get real parallelism here without any free-threading dependency.
    This matters at real scale — sequential provisioning of 32 services, repeated per active
    channel, is the difference between an install that finishes and one an operator abandons.

    Never raises for a service-level failure. The caller decides what an incomplete report
    means; `ProvisionReport.fully_provisioned` is the gate Supervisor needs before cutover.

    `inference_device` (§8.6) only ever changes `core.inference`'s own venv — see
    `provision_service`'s own docstring.
    """
    specs = discover_services(clone_root)
    if not specs:
        return ProvisionReport(outcomes=())

    workers = max_workers if max_workers is not None else min(8, len(specs))
    if workers <= 1:
        return ProvisionReport(
            outcomes=tuple(
                provision_service(s, python_bin=python_bin, upgrade=upgrade, inference_device=inference_device)
                for s in specs
            )
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                provision_service, s, python_bin=python_bin, upgrade=upgrade,
                inference_device=inference_device,
            ): s
            for s in specs
        }
        by_path = {futures[f].import_path: f.result() for f in futures}

    # Reported in discovery order, not completion order — a report whose ordering shifts run to
    # run is far harder to diff against a previous one when chasing a regression.
    return ProvisionReport(outcomes=tuple(by_path[s.import_path] for s in specs))


#: Live-found: a bare PyPI network blip (a CDN edge returning the wrong Content-Type for
#: one index page, mid a concurrent 8-way provisioning run) failed `pip install` outright
#: with no retry, taking the whole finalize down over something that succeeded on the very
#: next attempt with no code change at all. `pip install` is safe to re-run -- partially
#: installed packages are left in a state the next invocation resolves correctly, the same
#: idempotent-and-safely-re-runnable guarantee this module's own docstring already claims
#: for the outer `provision_service` call. A genuinely broken requirement (a real missing
#: wheel, an unsatisfiable pin) fails identically on every attempt, so retrying never masks
#: that -- it only costs the bounded extra time below before surfacing the same real error.
PIP_INSTALL_ATTEMPTS = 3
PIP_INSTALL_RETRY_DELAY_SECONDS = 3.0


def _run_with_retries(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    result = _run(cmd)
    attempt = 1
    while result.returncode != 0 and attempt < PIP_INSTALL_ATTEMPTS:
        time.sleep(PIP_INSTALL_RETRY_DELAY_SECONDS)
        result = _run(cmd)
        attempt += 1
    return result


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _stderr_of(result: subprocess.CompletedProcess[str]) -> str:
    """The subprocess's real output, never a paraphrase.

    Falls back to stdout because pip reports resolution failures there in some versions, and an
    empty `detail` is the outcome this whole error-as-data surface exists to avoid.
    """
    return (result.stderr or result.stdout or "").strip() or "no output captured"

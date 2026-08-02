"""Provisioning behaviour for per-service venvs (`docs/VENV_AND_IMPORTS.md` §4, §5).

Provisioning runs once per clone per channel and then never again until the next update, which
means a bug here is discovered at the worst possible moment — during a rollout, against a clone
that is about to be cut over to. The properties pinned below are the ones that decide whether a
bad clone fails *loudly and specifically* (actionable) or *late and vaguely* (not).

Real venvs are created on disk here rather than mocked. `venv` and `pip` are precisely the
things whose real behaviour this module exists to wrap, and a fake of them would pass while the
real pair failed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from services.setup.contracts import (
    ProvisionErrorCode,
    ProvisionOutcome,
    ProvisionReport,
    ServiceVenvSpec,
)
from services.setup.venv_provisioning import (
    BASE_REQUIREMENTS_RELPATH,
    discover_services,
    provision_clone,
    provision_service,
    venv_python,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _clone_with(tmp_path: Path, dotted: str, *, base: str = "", own: str | None = None) -> Path:
    root = tmp_path / "x02.01.03_a1b2c3d"
    base_path = root / BASE_REQUIREMENTS_RELPATH
    base_path.parent.mkdir(parents=True, exist_ok=True)
    base_path.write_text(base, encoding="utf-8")

    tree, name = dotted.split(".", 1)
    pkg = root / tree / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    if own is not None:
        (pkg / "requirements.txt").write_text(own, encoding="utf-8")
    return root


# --- the shared base's own content -------------------------------------------------------


def test_the_shared_base_declares_protobuf_explicitly_not_via_grpcio():
    """`grpcio` does NOT depend on `protobuf` — its only link is an optional `[protobuf]` extra
    that pulls `grpcio-tools`. The reason `google.protobuf` imports appear to "just work" in a
    dev checkout is that `grpcio-tools` drags protobuf in as a side effect.

    A service venv installing `grpcio` alone therefore import-fails on its own generated
    `*_pb2.py` stubs at startup. This test exists because that line looks redundant to anyone
    checking `pip list` in a dev environment where `grpcio-tools` is present, and "tidying it
    up" would break every gRPC service in the fleet at once, at Boot Sequence, with an error
    pointing at generated code rather than at the dependency list.
    """
    declared = (REPO_ROOT / "common" / "requirements.txt").read_text(encoding="utf-8")
    lines = [
        ln.split("#")[0].strip()
        for ln in declared.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    names = [ln.split(";")[0].split(">")[0].split("=")[0].split("<")[0].strip() for ln in lines]

    assert "protobuf" in names, "runtime base must declare protobuf itself, not inherit it"
    assert "grpcio" in names


def test_the_shared_base_does_not_ship_the_protoc_toolchain_to_every_service():
    """`grpcio-tools` is the code generator — build-time tooling. Putting it in the runtime base
    would replicate a compiler toolchain across 32 services × every simultaneously-active
    release clone (`docs/VENV_AND_IMPORTS.md` §2's cost note), for something no running service
    ever calls.
    """
    declared = (REPO_ROOT / "common" / "requirements.txt").read_text(encoding="utf-8")
    active = [ln for ln in declared.splitlines() if ln.strip() and not ln.strip().startswith("#")]

    assert not any("grpcio-tools" in ln for ln in active)


# --- failures are data --------------------------------------------------------------------


def test_a_missing_source_directory_is_reported_as_data_not_raised(tmp_path):
    """Errors are data at API boundaries (`docs/PRINCIPLES.md` §4.1). Provisioning a 32-service
    clone must not abort on the first bad service — an operator deciding whether the clone is
    salvageable needs the whole picture, and an exception here would deny them every outcome
    after the failing one.
    """
    spec = ServiceVenvSpec(
        import_path="core.ghost",
        source_dir=tmp_path / "does" / "not" / "exist",
        venv_dir=tmp_path / ".venvs" / "core.ghost",
        requirement_files=(),
    )
    outcome = provision_service(spec)

    assert isinstance(outcome, ProvisionOutcome)
    assert outcome.error is not None
    assert outcome.error.code is ProvisionErrorCode.SOURCE_DIR_MISSING
    assert not outcome.venv_dir.exists()


@pytest.mark.slow
def test_a_dependency_failure_carries_the_real_tool_output_not_a_paraphrase(tmp_path):
    """V2 discarded tracebacks in favour of `str(e)`, and the audit named that as a concrete
    cause of hard debugging (`v3-plan-04-v2-audit-findings.md`). The same applies to a
    subprocess's stderr: "install failed" is unactionable, whereas pip's own parse error names
    the offending line.
    """
    root = _clone_with(tmp_path, "core.broken", base=">>>not a valid requirement<<<\n")
    (spec,) = discover_services(root)
    outcome = provision_service(spec)

    assert outcome.error is not None
    assert outcome.error.code is ProvisionErrorCode.DEPENDENCY_INSTALL_FAILED
    assert outcome.error.detail.strip()
    assert outcome.error.detail != "no output captured"
    assert "requirements.txt" in outcome.error.detail


@pytest.mark.slow
def test_one_failing_service_does_not_suppress_the_others_outcomes(tmp_path):
    """The whole point of a report rather than an exception."""
    root = _clone_with(tmp_path, "core.fine", base="")
    bad = root / "core" / "broken"
    bad.mkdir(parents=True)
    (bad / "__init__.py").write_text("", encoding="utf-8")
    (bad / "requirements.txt").write_text(">>>invalid<<<\n", encoding="utf-8")

    report = provision_clone(root, max_workers=1)

    assert {o.import_path for o in report.outcomes} == {"core.fine", "core.broken"}
    assert not report.fully_provisioned
    assert {o.import_path for o in report.failed} == {"core.broken"}


def test_a_clone_is_not_cutover_eligible_while_any_service_is_unprovisioned():
    """`fully_provisioned` is the gate Supervisor needs before cutover. A service whose venv is
    half-built is not a degraded service, it is an import error at launch — so this is one of
    the few deliberately fail-closed paths outside security (`docs/VENV_AND_IMPORTS.md` §5).
    """
    ok = ProvisionOutcome(import_path="core.a", venv_dir=Path("a"), created=True)
    report = ProvisionReport(outcomes=(ok,))
    assert report.fully_provisioned

    from services.setup.contracts import ProvisionError

    bad = ProvisionOutcome(
        import_path="core.b",
        venv_dir=Path("b"),
        created=False,
        error=ProvisionError(code=ProvisionErrorCode.VENV_CREATION_FAILED, detail="boom"),
    )
    assert not ProvisionReport(outcomes=(ok, bad)).fully_provisioned


# --- ordering, idempotence, platform ------------------------------------------------------


@pytest.mark.slow
def test_outcomes_are_reported_in_discovery_order_not_completion_order(tmp_path):
    """Provisioning runs concurrently, so completion order is genuinely nondeterministic. A
    report whose row order shifts between runs cannot be diffed against a previous one, which is
    exactly what an operator does when chasing why a clone stopped provisioning cleanly.
    """
    root = _clone_with(tmp_path, "core.alpha", base="")
    for name in ("beta", "gamma", "delta"):
        pkg = root / "core" / name
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")

    expected = [s.import_path for s in discover_services(root)]
    report = provision_clone(root, max_workers=4)

    assert [o.import_path for o in report.outcomes] == expected


def test_venv_python_points_at_the_right_place_for_this_platform(tmp_path):
    """Windows puts the interpreter in `Scripts/`, POSIX in `bin/`. Getting this wrong makes
    every provisioned venv report `INTERPRETER_UNUSABLE` immediately after a successful create —
    a confusing failure that looks like `venv` misbehaving rather than a path assumption.
    """
    path = venv_python(tmp_path / "v")
    assert path.parent.name == ("Scripts" if os.name == "nt" else "bin")
    assert path.parent.parent == tmp_path / "v"


@pytest.mark.slow
def test_provisioning_is_idempotent_and_creates_a_genuinely_usable_interpreter(tmp_path):
    """The end-to-end guarantee, against real `venv` and real `pip`.

    Two things at once, because they are the same run: the created venv must contain an
    interpreter that actually executes, and a second provisioning pass must leave it alone
    (`created=False`) rather than rebuilding it. Re-running after a partial failure is a normal,
    safe operation (`v3-deepdive-11-setup-api.md` §4's re-runnability property) — without
    idempotence it would silently discard every already-working environment in the clone.
    """
    root = _clone_with(tmp_path, "core.tiny", base="", own="")
    (spec,) = discover_services(root)

    first = provision_service(spec)
    assert first.error is None, first.error
    assert first.created is True

    py = venv_python(spec.venv_dir)
    assert py.exists()

    import subprocess

    proof = subprocess.run(
        [str(py), "-c", "import sys; print(sys.prefix)"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proof.returncode == 0, proof.stderr
    assert str(spec.venv_dir) in proof.stdout.strip()

    second = provision_service(spec)
    assert second.error is None
    assert second.created is False, "an existing venv must be left alone, not rebuilt"


@pytest.mark.slow
def test_the_running_interpreter_is_the_default_when_none_is_given(tmp_path):
    """Provisioning defaults to `sys.executable` so a clone is built against the interpreter
    that is actually running the install, not whatever `python` happens to resolve to on PATH.
    On this project's own Windows targets those genuinely differ — `python` can resolve to a
    Store shim while the real install runs elsewhere.
    """
    root = _clone_with(tmp_path, "core.tiny", base="")
    (spec,) = discover_services(root)
    outcome = provision_service(spec, python_bin=str(Path(sys.executable)))

    assert outcome.error is None, outcome.error

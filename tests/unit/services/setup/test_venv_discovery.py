"""Service discovery for per-service venv provisioning (`docs/VENV_AND_IMPORTS.md` §2, §4).

Discovery is the half of provisioning that decides *what gets a venv at all*. Getting it wrong
is quiet rather than loud: a service silently skipped here has no venv, and the failure does not
surface until Supervisor tries to launch it and the import fails at Boot Sequence — well past
the point where the useful error was available.

These build a real temporary clone tree on disk rather than mocking the filesystem, per the
suite-wide rule against stubbing the thing under test.
"""

from __future__ import annotations

from pathlib import Path

from services.setup.venv_provisioning import (
    BASE_REQUIREMENTS_RELPATH,
    VENVS_DIRNAME,
    discover_services,
)


def _clone(tmp_path: Path, *, packages: dict[str, dict[str, str]], base: str | None = "grpcio\n") -> Path:
    """Build a minimal but real clone tree.

    `packages` maps a dotted path like `core.ocr` to the files that package contains.
    """
    root = tmp_path / "x02.01.03_a1b2c3d"
    if base is not None:
        base_path = root / BASE_REQUIREMENTS_RELPATH
        base_path.parent.mkdir(parents=True, exist_ok=True)
        base_path.write_text(base, encoding="utf-8")
    for dotted, files in packages.items():
        tree, name = dotted.split(".", 1)
        pkg = root / tree / name
        pkg.mkdir(parents=True, exist_ok=True)
        for filename, content in files.items():
            (pkg / filename).write_text(content, encoding="utf-8")
    return root


def test_a_service_in_each_tree_is_discovered_not_just_the_core_one(tmp_path):
    """`services/` holds real launchable processes too — Gateway and Interface are Layer 2, and
    Setup and Update live there as well (`docs/PROCESS_TOPOLOGY.md` §2). Discovering only
    `core/` would leave every one of them without a venv while the report still claimed success.
    """
    root = _clone(
        tmp_path,
        packages={
            "core.ocr": {"__init__.py": ""},
            "services.gateway": {"__init__.py": ""},
        },
    )
    assert {s.import_path for s in discover_services(root)} == {"core.ocr", "services.gateway"}


def test_the_same_leaf_name_in_both_trees_yields_two_distinct_venvs(tmp_path):
    """Nothing structurally stops `core/` and `services/` holding the same leaf name.

    `execution_core` was in both trees until it was consolidated into `services/` to match its
    own deep-dive §2 — so this is a collision this repo has actually had, not an invented one.
    If the venv directory were named for the bare leaf, two such packages would collide on one
    path and whichever provisioned second would silently overwrite the first's environment — a
    corruption whose symptom shows up in whichever service was unlucky, not in the one that
    caused it. The dotted `import_path` naming is what prevents that.
    """
    root = _clone(
        tmp_path,
        packages={
            "core.shared_name": {"__init__.py": ""},
            "services.shared_name": {"__init__.py": ""},
        },
    )
    specs = discover_services(root)
    venv_dirs = {s.venv_dir for s in specs}

    assert len(specs) == 2
    assert len(venv_dirs) == 2, "leaf-name collision would have merged these into one venv"
    assert {s.venv_dir.name for s in specs} == {"core.shared_name", "services.shared_name"}


def test_requirement_files_put_the_shared_base_before_the_services_own(tmp_path):
    """Order is not cosmetic: pip resolves later requirements against what earlier ones pinned.

    Installing a service's own file first would let it pin a transitive dependency that the
    shared base then has to satisfy in reverse, which is how two services on the same base end
    up with genuinely different resolved versions of it (`docs/VENV_AND_IMPORTS.md` §4).
    """
    root = _clone(
        tmp_path,
        packages={"core.auth": {"__init__.py": "", "requirements.txt": "authlib>=1.3\n"}},
    )
    (spec,) = discover_services(root)

    assert [p.name for p in spec.requirement_files] == ["requirements.txt", "requirements.txt"]
    assert spec.requirement_files[0] == root / BASE_REQUIREMENTS_RELPATH
    assert spec.requirement_files[1] == root / "core" / "auth" / "requirements.txt"


def test_a_service_with_no_requirements_file_of_its_own_is_valid_and_gets_the_base(tmp_path):
    """A pinned NON-finding, deliberately.

    Most services need nothing beyond the shared base — of the sixteen packages implemented
    today only five do. A validation pass that treated a missing `requirements.txt` as an error,
    or that skipped such a service entirely, would break the majority case while looking like it
    had tightened something up.
    """
    root = _clone(tmp_path, packages={"core.audit": {"__init__.py": ""}})
    (spec,) = discover_services(root)

    assert len(spec.requirement_files) == 1
    assert spec.requirement_files[0] == root / BASE_REQUIREMENTS_RELPATH


def test_a_scaffolded_package_with_only_empty_files_is_still_discovered(tmp_path):
    """Another pinned NON-finding.

    Five packages in this repo are 0-byte Phase-1 scaffolding right now. Discovery that quietly
    skipped "empty" packages would make the provisioning report disagree with what the clone
    actually contains — and this project has been bitten specifically by prose that disagreed
    with the real inventory. Discovery reports what is there.
    """
    root = _clone(tmp_path, packages={"core.ocr": {"__init__.py": "", "service.py": ""}})
    assert [s.import_path for s in discover_services(root)] == ["core.ocr"]


def test_a_directory_that_is_not_a_package_is_not_mistaken_for_a_service(tmp_path):
    """`core/` and `services/` can hold non-package directories — `generated/` output, stray
    tooling. Handing one of those a venv would waste real install time per clone per channel and
    put a nonsense entry in every provisioning report.
    """
    root = _clone(tmp_path, packages={"core.ocr": {"__init__.py": ""}})
    (root / "core" / "scratch").mkdir()
    (root / "core" / "scratch" / "notes.txt").write_text("no __init__", encoding="utf-8")

    assert [s.import_path for s in discover_services(root)] == ["core.ocr"]


def test_dunder_and_dot_directories_are_skipped(tmp_path):
    """`__pycache__` sits next to real packages after any test run, and `.venvs/` is created by
    provisioning itself — inside the very tree being scanned. Without this, a second
    provisioning run would discover its own output as a service to provision.
    """
    root = _clone(tmp_path, packages={"core.ocr": {"__init__.py": ""}})
    for noise in ("__pycache__", ".mypy_cache"):
        d = root / "core" / noise
        d.mkdir()
        (d / "__init__.py").write_text("", encoding="utf-8")

    assert [s.import_path for s in discover_services(root)] == ["core.ocr"]


def test_the_venvs_directory_lives_inside_the_clone_it_serves(tmp_path):
    """Venvs are pinned to the exact dependency versions their clone's code expects, so they
    cannot be shared across clones (`docs/VENV_AND_IMPORTS.md` §2).

    Placing them outside the clone would also break the never-mutate-a-served-release guarantee
    that makes concurrent multi-channel operation safe
    (`v3-deepdive-24-update-deployment-api.md` §3) — provisioning a new clone would be writing
    into an environment a running process is importing from.
    """
    root = _clone(tmp_path, packages={"core.ocr": {"__init__.py": ""}})
    (spec,) = discover_services(root)

    assert spec.venv_dir.parent == root / VENVS_DIRNAME
    assert root in spec.venv_dir.parents


def test_discovery_of_a_clone_with_no_base_requirements_file_still_reports_services(tmp_path):
    """Degrade rather than vanish. A clone missing the shared base is a real problem, but the
    right shape for it is a service that reports an install failure with a name attached, not a
    discovery pass that returns nothing and reads as "this clone has no services."
    """
    root = _clone(tmp_path, packages={"core.ocr": {"__init__.py": ""}}, base=None)
    (spec,) = discover_services(root)

    assert spec.import_path == "core.ocr"
    assert spec.requirement_files == ()

"""The finalize routine (`v3-deepdive-11-setup-api.md` §4, §7.4).

`cleanup_top_level_setup_files` deletes files from the TOP-LEVEL install directory — a sibling
of `config/`, `data/` and `models/`, per `docs/PRINCIPLES.md` §1.6 — so containment gets the same
seriousness `test_dev_mode_strip.py` gives the clone-internal strip: this is real user data one
directory away, not a hypothetical.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from services.setup.bootstrap import (
    INSTALL_CONFIG_RELPATH,
    LAUNCHER_SCRIPT_NAMES,
    TOP_LEVEL_SETUP_FILES,
    cleanup_top_level_setup_files,
    copy_launcher_scripts,
    finalize_clone,
    read_dev_mode,
    write_install_config,
)
from services.setup.venv_provisioning import BASE_REQUIREMENTS_RELPATH


def _install_root_with_clone(tmp_path: Path) -> tuple[Path, Path]:
    install_root = tmp_path / "install"
    clone = install_root / "releases" / "x02.01.03_a1b2c3d"
    for d in ("core/ocr", "services/setup"):
        (clone / d).mkdir(parents=True, exist_ok=True)
        (clone / d / "__init__.py").write_text("", encoding="utf-8")
    base_req = clone / BASE_REQUIREMENTS_RELPATH
    base_req.parent.mkdir(parents=True, exist_ok=True)
    base_req.write_text("", encoding="utf-8")
    for f in ("docs/apis/deepdive.md", "tests/unit/test_x.py", ".github/scripts/check.py"):
        p = clone / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    return install_root, clone


class _FakeWebappBuilder:
    def __init__(self):
        self.called_with: Path | None = None

    async def build(self, clone_dir: Path) -> None:
        self.called_with = clone_dir


# --- cleanup_top_level_setup_files ---------------------------------------------------------


def test_removes_every_present_setup_file_and_reports_which(tmp_path):
    install_root, _ = _install_root_with_clone(tmp_path)
    for name in ("setup.bat", "setup-dev.sh"):
        (install_root / name).write_text("x", encoding="utf-8")

    removed = cleanup_top_level_setup_files(install_root)

    assert set(removed) == {"setup.bat", "setup-dev.sh"}
    assert not (install_root / "setup.bat").exists()
    assert not (install_root / "setup-dev.sh").exists()


def test_a_second_run_with_nothing_left_to_remove_succeeds_not_errors(tmp_path):
    """Idempotence, the same property every other Setup mechanism in this package has."""
    install_root, _ = _install_root_with_clone(tmp_path)
    (install_root / "setup.bat").write_text("x", encoding="utf-8")

    first = cleanup_top_level_setup_files(install_root)
    second = cleanup_top_level_setup_files(install_root)

    assert first == ("setup.bat",)
    assert second == ()


def test_only_the_exact_allowlisted_names_are_ever_touched(tmp_path):
    """Containment: the top-level install directory holds config/, data/ and models/ as
    siblings of every release clone (`docs/PRINCIPLES.md` §1.6). A glob-based match here would
    be the kind of thing that quietly grows to catch something it should not; this pins the
    allowlist as exact-name, not pattern-based.
    """
    install_root, _ = _install_root_with_clone(tmp_path)
    decoy = install_root / "setup_notes.txt"  # contains "setup" but is not in the allowlist
    decoy.write_text("do not delete me", encoding="utf-8")
    config_dir = install_root / "config"
    config_dir.mkdir()
    (config_dir / "real_user_config.json").write_text('{"real": true}', encoding="utf-8")

    cleanup_top_level_setup_files(install_root)

    assert decoy.exists()
    assert (config_dir / "real_user_config.json").exists()


def test_the_allowlist_matches_section_4s_own_five_named_files():
    assert TOP_LEVEL_SETUP_FILES == {
        "setup.bat",
        "setup.sh",
        "setup-dev.bat",
        "setup-dev.sh",
        "setup.ps1",
        "setup-dev.ps1",
    }


# --- finalize_clone -------------------------------------------------------------------------


@pytest.mark.slow
def test_finalize_runs_strip_provision_and_cleanup_in_order_with_no_webapp_builder(tmp_path):
    """The webapp step is optional — `services/gateway/` is 0-byte scaffolding as of this
    module's own build, so a `None` builder must degrade that one step, not fail the whole
    routine (`docs/PRINCIPLES.md` §4.4). Runs real venv creation, hence `slow`.
    """
    install_root, clone = _install_root_with_clone(tmp_path)
    (install_root / "setup.bat").write_text("x", encoding="utf-8")

    report = asyncio.run(finalize_clone(clone, dev_mode=False))

    assert report.strip.ok
    assert "docs" in report.strip.removed
    assert report.venv_provision.fully_provisioned, report.venv_provision.failed
    assert report.webapp_built is False
    assert report.top_level_files_cleaned == ("setup.bat",)
    assert report.ok


@pytest.mark.slow
def test_finalize_calls_the_webapp_builder_when_one_is_supplied(tmp_path):
    _, clone = _install_root_with_clone(tmp_path)
    builder = _FakeWebappBuilder()

    report = asyncio.run(finalize_clone(clone, dev_mode=False, webapp_builder=builder))

    assert report.webapp_built is True
    assert builder.called_with == clone


@pytest.mark.slow
def test_dev_mode_skips_stripping_but_the_rest_of_finalize_still_runs(tmp_path):
    """A developer checkout needs its docs/tests/CI scaffolding intact, but venv provisioning
    and top-level cleanup are not development-only concerns — they still run.
    """
    install_root, clone = _install_root_with_clone(tmp_path)

    report = asyncio.run(finalize_clone(clone, dev_mode=True))

    assert report.strip.removed == ()
    assert (clone / "docs").exists()
    assert report.venv_provision.fully_provisioned, report.venv_provision.failed


@pytest.mark.slow
def test_finalize_report_is_not_ok_when_any_underlying_step_failed(tmp_path):
    """`BootstrapReport.ok` is the gate Supervisor's Boot Sequence needs. A malformed venv
    requirements file must make the whole report ineligible, not just the one service.
    """
    install_root, clone = _install_root_with_clone(tmp_path)
    broken = clone / "core" / "broken"
    broken.mkdir(parents=True)
    (broken / "__init__.py").write_text("", encoding="utf-8")
    (broken / "requirements.txt").write_text(">>>invalid<<<\n", encoding="utf-8")

    report = asyncio.run(finalize_clone(clone, dev_mode=True))

    assert not report.venv_provision.fully_provisioned
    assert not report.ok


# --- copy_launcher_scripts -------------------------------------------------------------------


def test_launcher_scripts_present_in_the_clone_are_copied_to_the_install_root(tmp_path):
    install_root, clone = _install_root_with_clone(tmp_path)
    (clone / "start.sh").write_text("#!/usr/bin/env bash\necho real launcher\n", encoding="utf-8")
    (clone / "start.bat").write_text("@echo off\r\necho real launcher\r\n", encoding="utf-8")

    copied = copy_launcher_scripts(clone, install_root)

    assert set(copied) == LAUNCHER_SCRIPT_NAMES
    assert (install_root / "start.sh").read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho real launcher\n"
    assert (install_root / "start.bat").exists()


def test_a_missing_launcher_script_in_the_clone_is_skipped_not_fatal(tmp_path):
    install_root, clone = _install_root_with_clone(tmp_path)
    (clone / "start.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    # start.bat deliberately absent

    copied = copy_launcher_scripts(clone, install_root)

    assert copied == ("start.sh",)
    assert not (install_root / "start.bat").exists()


def test_re_running_copy_launcher_scripts_overwrites_with_the_newer_clones_version(tmp_path):
    """Every update is a fresh clone; the install root's own launcher should track whichever
    clone most recently finalized, not silently keep serving a stale copy from the first
    install."""
    install_root, clone = _install_root_with_clone(tmp_path)
    (clone / "start.sh").write_text("v1\n", encoding="utf-8")
    copy_launcher_scripts(clone, install_root)

    (clone / "start.sh").write_text("v2\n", encoding="utf-8")
    copy_launcher_scripts(clone, install_root)

    assert (install_root / "start.sh").read_text(encoding="utf-8") == "v2\n"


# --- write_install_config / read_dev_mode ----------------------------------------------------


def test_write_install_config_persists_dev_mode_and_read_dev_mode_reads_it_back(tmp_path):
    written = write_install_config(tmp_path, dev_mode=True)
    assert written is True
    assert read_dev_mode(tmp_path) is True

    target = tmp_path / INSTALL_CONFIG_RELPATH
    assert target.is_file()


def test_write_install_config_never_overwrites_an_existing_config():
    """§4.1: "recorded once, at first-clone time... not something asked again on every
    subsequent update." A later finalize call with a *different* dev_mode value must not flip
    an already-installed instance's own persisted choice."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = write_install_config(root, dev_mode=False)
        second = write_install_config(root, dev_mode=True)

        assert first is True
        assert second is False
        assert read_dev_mode(root) is False


def test_read_dev_mode_returns_none_when_no_config_exists_yet(tmp_path):
    """Distinct from `False` — "not yet installed" and "installed in normal mode" are different
    facts a caller needs to tell apart."""
    assert read_dev_mode(tmp_path) is None


def test_read_dev_mode_returns_none_for_a_corrupted_config_rather_than_raising(tmp_path):
    target = tmp_path / INSTALL_CONFIG_RELPATH
    target.parent.mkdir(parents=True)
    target.write_text("not valid json{{{", encoding="utf-8")

    assert read_dev_mode(tmp_path) is None


# --- finalize_clone now includes both new steps -----------------------------------------------


@pytest.mark.slow
def test_finalize_clone_copies_launchers_and_writes_install_config(tmp_path):
    install_root, clone = _install_root_with_clone(tmp_path)
    (clone / "start.sh").write_text("real launcher\n", encoding="utf-8")

    report = asyncio.run(finalize_clone(clone, dev_mode=False))

    assert report.launcher_scripts_copied == ("start.sh",)
    assert (install_root / "start.sh").exists()
    assert report.install_config_written is True
    assert read_dev_mode(install_root) is False

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
    TOP_LEVEL_SETUP_FILES,
    cleanup_top_level_setup_files,
    finalize_clone,
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

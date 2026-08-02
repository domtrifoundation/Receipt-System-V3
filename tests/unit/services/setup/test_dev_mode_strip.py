"""`strip_development_content()` (`v3-deepdive-11-setup-api.md` §4.1).

This function deletes directory trees inside a clone, and the top-level installation directory —
config, user receipts, model weights — is a *sibling* of every release clone
(`docs/PRINCIPLES.md` §1.6). That adjacency is why the containment test below exists and why it
is not paranoia: the blast radius of a path bug here is a user's financial records.

Real trees on disk, real deletions, in `tmp_path`. Mocking the filesystem would test the mock.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from services.setup.dev_mode_strip import (
    DEV_ONLY_STRIP_LIST,
    NESTED_STRIP_FILENAMES,
    SHIPPED_ALLOWLIST,
    strip_development_content,
)
from services.setup.errors import StripErrorCode


def _clone(tmp_path: Path) -> Path:
    """A clone carrying one of everything: shipped dirs, dev-only dirs, nested CLAUDE.md."""
    root = tmp_path / "install" / "releases" / "x02.01.03_a1b2c3d"
    for d in ("core/ocr", "services/setup", "common", "docs/apis", "tests/unit", ".github/scripts"):
        (root / d).mkdir(parents=True, exist_ok=True)
    for f in (
        "CLAUDE.md",
        "CONTRIBUTING.md",
        "README.md",
        "pytest.ini",
        "noxfile.py",
        "requirements.txt",
        "start.sh",
        "core/ocr/CLAUDE.md",
        "services/setup/CLAUDE.md",
        "core/ocr/service.py",
        "docs/apis/deepdive.md",
        "tests/unit/test_x.py",
        ".github/scripts/check.py",
    ):
        (root / f).write_text("x", encoding="utf-8")
    return root


def test_developer_mode_strips_absolutely_nothing(tmp_path):
    """A contributor working in the clone needs the full docs corpus, test tree and CI
    scaffolding (`v3-deepdive-11-setup-api.md` §4.1). The flag is recorded once at first clone
    and read by every later one, so getting this branch wrong would silently gut a developer's
    checkout on their next update rather than at install time.
    """
    root = _clone(tmp_path)
    report = strip_development_content(root, dev_mode=True)

    assert report.ok
    assert report.removed == ()
    assert (root / "docs").is_dir()
    assert (root / "tests").is_dir()
    assert (root / "CLAUDE.md").exists()
    assert (root / "core" / "ocr" / "CLAUDE.md").exists()


def test_normal_mode_removes_every_dev_only_entry_and_keeps_every_shipped_one(tmp_path):
    """The core guarantee, asserted in both directions.

    Checking only that dev-only content disappeared would pass for a function that deleted the
    whole clone — so what ships must be asserted to survive, not assumed.
    """
    root = _clone(tmp_path)
    report = strip_development_content(root, dev_mode=False)

    assert report.ok, report.errors
    assert not (root / "docs").exists()
    assert not (root / "tests").exists()
    assert not (root / ".github").exists()
    assert not (root / "pytest.ini").exists()
    assert not (root / "noxfile.py").exists()
    assert not (root / "CONTRIBUTING.md").exists()

    assert (root / "core" / "ocr" / "service.py").exists()
    assert (root / "common").is_dir()
    assert (root / "README.md").exists()
    assert (root / "requirements.txt").exists()
    assert (root / "start.sh").exists()


def test_nested_claude_md_files_are_stripped_not_just_the_top_level_one(tmp_path):
    """The gap `check_stripped_content_list.py` flagged for whoever implemented this module.

    52 `CLAUDE.md` files live nested under `core/`, `services/`, `webapp/` and `supervisor/` —
    all of which ship. A top-level entry name cannot express "strip this filename wherever it
    appears," so without a nested rule every end-user install would carry 52 development-only
    files it never reads, while the top-level check reported success.
    """
    root = _clone(tmp_path)
    report = strip_development_content(root, dev_mode=False)

    assert not (root / "CLAUDE.md").exists()
    assert not (root / "core" / "ocr" / "CLAUDE.md").exists()
    assert not (root / "services" / "setup" / "CLAUDE.md").exists()
    assert "core/ocr/CLAUDE.md" in report.removed
    assert (root / "core" / "ocr").is_dir(), "stripping a file must not take its directory"


def test_stripping_an_already_stripped_clone_succeeds_instead_of_failing(tmp_path):
    """Idempotence is not a nicety here. Update API strips every fresh clone and Setup is
    explicitly re-runnable (`v3-deepdive-11-setup-api.md` §4), so the second pass is a normal
    operation. Treating an already-absent entry as an error would fail a rollout for having
    already succeeded.
    """
    root = _clone(tmp_path)
    first = strip_development_content(root, dev_mode=False)
    second = strip_development_content(root, dev_mode=False)

    assert first.ok and second.ok
    assert second.removed == ()
    assert set(second.skipped_absent) >= {"docs", "tests", ".github"}


def test_absent_is_reported_separately_from_removed(tmp_path):
    """A pinned distinction, deliberately.

    Folding "it was never there" into "I removed it" would leave the report unable to answer
    whether a strip actually did anything — which is the one question an operator asks when a
    shipped install still contains `docs/`.
    """
    root = tmp_path / "bare"
    (root / "core").mkdir(parents=True)
    report = strip_development_content(root, dev_mode=False)

    assert report.ok
    assert report.removed == ()
    assert set(report.skipped_absent) == set(DEV_ONLY_STRIP_LIST)


def test_nothing_outside_the_clone_is_ever_touched(tmp_path):
    """The containment guarantee, against the real adjacency it protects.

    The top-level install directory holds `config/`, `data/` and `models/` as siblings of every
    release clone (`docs/PRINCIPLES.md` §1.6). A traversal bug here does not corrupt a build —
    it deletes a user's receipts. This builds that exact layout and asserts the siblings survive.
    """
    root = _clone(tmp_path)
    install_root = root.parent.parent
    for sibling in ("config", "data", "models"):
        d = install_root / sibling
        d.mkdir(parents=True, exist_ok=True)
        (d / "user.db").write_text("real user data", encoding="utf-8")

    report = strip_development_content(root, dev_mode=False)

    assert report.ok, report.errors
    for sibling in ("config", "data", "models"):
        assert (install_root / sibling / "user.db").read_text(encoding="utf-8") == "real user data"


def test_a_dev_only_entry_resolving_outside_the_clone_is_refused_not_deleted(tmp_path):
    """A symlinked dev-only entry pointing out of the clone must be refused with its own error
    code, not followed.

    `PATH_ESCAPES_CLONE` is deliberately distinct from a generic removal failure: a permission
    error is worth retrying, an escape means the input was malformed and retrying is exactly the
    wrong response.
    """
    root = _clone(tmp_path)
    outside = tmp_path / "outside_treasure"
    outside.mkdir()
    (outside / "keep.txt").write_text("must survive", encoding="utf-8")

    shutil.rmtree(root / "docs")
    try:
        (root / "docs").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform/account cannot create symlinks; guard is untestable here")

    report = strip_development_content(root, dev_mode=False)

    assert (outside / "keep.txt").exists(), "content outside the clone was deleted"
    assert any(e.code is StripErrorCode.PATH_ESCAPES_CLONE for e in report.errors)
    assert not report.ok


def test_the_two_classification_lists_do_not_overlap():
    """An entry in both lists is a contradiction the strip cannot resolve — it would be deleted
    and expected to survive at the same time. CI checks this too; pinning it here means a local
    edit fails immediately rather than at push time.
    """
    assert not (SHIPPED_ALLOWLIST & DEV_ONLY_STRIP_LIST)


def test_no_nested_strip_filename_is_also_classified_shipped():
    """Worse than a top-level overlap and invisible to that check.

    A nested-strip filename is removed wherever it appears, so one that is also shipped would
    delete shipped content repo-wide while the two top-level lists remained disjoint.
    """
    assert not (NESTED_STRIP_FILENAMES & SHIPPED_ALLOWLIST)

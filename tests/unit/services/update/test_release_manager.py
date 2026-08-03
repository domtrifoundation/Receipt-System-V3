"""`release_manager.py` — the real clone/finalize/GC pipeline. `CLAUDE.md`'s own "Real
gotchas" section named this file as the actual gap: `contracts.py` and
`keymaster_client.py` were real, `release_manager.py` was 0 bytes. Every test here clones
against a real local git repository (`conftest.py`'s `git_remote` fixture), never a mock.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import services.update.release_manager as rm
from services.update.contracts import ChannelName

from .conftest import run


@pytest.fixture(autouse=True)
def _point_at_test_remote(git_remote: Path, monkeypatch):
    monkeypatch.setattr(rm, "REPO_CLONE_URL", str(git_remote))


def test_resolve_channel_ref_finds_a_real_tag():
    ref, used_fallback = run(rm.resolve_channel_ref(ChannelName.STABLE))

    assert ref == "stable"
    assert used_fallback is False


def test_resolve_channel_ref_finds_a_real_ltsc_branch():
    ref, used_fallback = run(rm.resolve_channel_ref(ChannelName.LTSC))

    assert ref == "ltsc/2026"
    assert used_fallback is False


def test_resolve_channel_ref_falls_back_to_main_for_a_channel_with_no_tag_yet():
    ref, used_fallback = run(rm.resolve_channel_ref(ChannelName.BETA))

    assert ref == "main"
    assert used_fallback is True


def test_resolve_channel_ref_latest_commit_always_resolves_to_main():
    ref, used_fallback = run(rm.resolve_channel_ref(ChannelName.LATEST_COMMIT))

    assert ref == "main"
    assert used_fallback is False


def test_resolve_channel_ref_override_skips_resolution_entirely():
    ref, used_fallback = run(rm.resolve_channel_ref(ChannelName.STABLE, ref_override="ltsc/2026"))

    assert ref == "ltsc/2026"
    assert used_fallback is False


def test_clone_release_produces_a_real_named_directory(tmp_path: Path):
    install_root = tmp_path / "install"

    result = run(rm.clone_release(install_root, ChannelName.STABLE, dev_mode=True))

    assert result.ok is True
    assert result.error_code == ""
    assert result.release.path.is_dir()
    assert result.release.path.name == f"{result.release.version}_{result.release.commit_hash}"
    assert result.release.version == "x00.99.00"
    assert (result.release.path / "common" / "version.py").is_file()
    assert result.finalize is not None
    assert result.finalize.install_config_written is True


def test_clone_release_records_channel_usage(tmp_path: Path):
    install_root = tmp_path / "install"

    result = run(rm.clone_release(install_root, ChannelName.STABLE, dev_mode=True))
    active = rm.get_active_channels(install_root)

    assert len(active) == 1
    assert active[0].channel == ChannelName.STABLE
    assert active[0].last_release_name == result.release.path.name


def test_clone_release_reuses_dev_mode_from_an_existing_install(tmp_path: Path):
    install_root = tmp_path / "install"
    run(rm.clone_release(install_root, ChannelName.STABLE, dev_mode=True))

    # second clone with no dev_mode passed — must read the persisted True, not default False
    result = run(rm.clone_release(install_root, ChannelName.LTSC))

    assert result.ok is True


def test_clone_release_same_commit_twice_does_not_error_or_leave_a_stray_temp_dir(tmp_path: Path):
    install_root = tmp_path / "install"
    r1 = run(rm.clone_release(install_root, ChannelName.STABLE, dev_mode=True))
    r2 = run(rm.clone_release(install_root, ChannelName.STABLE))

    assert r1.ok and r2.ok
    assert r1.release.path == r2.release.path
    releases_dir = install_root / "releases"
    names = [p.name for p in releases_dir.iterdir()]
    assert all(not n.startswith(".bootstrap-clone-") for n in names)


def test_garbage_collect_releases_removes_unkept_directories_and_they_are_actually_gone(tmp_path: Path):
    install_root = tmp_path / "install"
    r1 = run(rm.clone_release(install_root, ChannelName.STABLE, dev_mode=True))

    releases_dir = install_root / "releases"
    removed = rm.garbage_collect_releases(releases_dir, keep=frozenset())

    assert removed == (r1.release.path.name,)
    assert not r1.release.path.exists()


def test_garbage_collect_releases_keeps_named_directories(tmp_path: Path):
    install_root = tmp_path / "install"
    r1 = run(rm.clone_release(install_root, ChannelName.STABLE, dev_mode=True))

    releases_dir = install_root / "releases"
    removed = rm.garbage_collect_releases(releases_dir, keep=frozenset({r1.release.path.name}))

    assert removed == ()
    assert r1.release.path.exists()


def test_garbage_collect_releases_on_a_missing_directory_returns_empty(tmp_path: Path):
    removed = rm.garbage_collect_releases(tmp_path / "no-such-dir", keep=frozenset())

    assert removed == ()


def test_get_active_channels_on_a_fresh_install_returns_empty(tmp_path: Path):
    active = rm.get_active_channels(tmp_path / "install")

    assert active == ()

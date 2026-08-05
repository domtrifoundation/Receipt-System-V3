from __future__ import annotations

from pathlib import Path

from common.install_paths import resolve_install_root


def test_finds_install_root_from_inside_a_release_clone(tmp_path: Path):
    module_path = tmp_path / "releases" / "x03.01.05_abc123" / "services" / "setup" / "service.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("", encoding="utf-8")

    assert resolve_install_root(module_path) == tmp_path


def test_returns_none_in_a_dev_checkout_with_no_releases_ancestor(tmp_path: Path):
    module_path = tmp_path / "git" / "Receipt-System-V3" / "services" / "setup" / "service.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("", encoding="utf-8")

    assert resolve_install_root(module_path) is None

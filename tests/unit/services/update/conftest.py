"""Shared fixtures for Update API's unit tests.

`git_remote` builds a real, local bare git repository with real commits, a real tag, and a
real branch — the same real-git discipline `release_manager.py`'s own module docstring
follows (mirroring `installer/common.sh`'s own live git usage). Every test in
`test_release_manager.py` clones against this real remote, never a mocked git call.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest


def run(coro):
    return asyncio.run(coro)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_remote(tmp_path: Path) -> Path:
    """A real bare repo at `tmp_path/remote.git`, with one commit on `main` (carrying a real
    `common/version.py`), a `stable` tag pointing at it, and an `ltsc/2026` branch."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git("init", "--bare", str(remote), cwd=tmp_path)
    _git("clone", str(remote), str(work), cwd=tmp_path)
    _git("checkout", "-b", "main", cwd=work)

    (work / "common").mkdir()
    (work / "common" / "version.py").write_text('PROGRAM_VERSION = "x00.99.00"\n', encoding="utf-8")
    (work / "README.md").write_text("test\n", encoding="utf-8")
    _git("-c", "user.email=t@t.com", "-c", "user.name=t", "add", "-A", cwd=work)
    _git("-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "init", cwd=work)
    _git("push", "origin", "main", cwd=work)
    _git("tag", "stable", cwd=work)
    _git("push", "origin", "stable", cwd=work)
    _git("checkout", "-b", "ltsc/2026", cwd=work)
    _git("push", "origin", "ltsc/2026", cwd=work)

    return remote

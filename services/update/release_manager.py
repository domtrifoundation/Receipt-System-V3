"""Produces a cloned, named, finalized release directory (`v3-deepdive-24-update-
deployment-api.md` §3) — this API's whole job, and nothing past it. Deciding whether to
*activate* what this module produces is Supervisor's call entirely
(`docs/apis/v3-deepdive-38-supervisor.md`), never this module's.

**Mirrors `installer/common.sh`'s own real, live-tested clone flow exactly, and the two
must never drift** (`docs/PRINCIPLES.md` §1.5) — that shell script is the necessary
pre-Python reference implementation of this same operation (it runs before this module is
even on disk, during the very first install), and this is the real, ongoing implementation
every subsequent Update API clone uses. Channel-to-ref resolution, the `<version>_<commit-
hash>` naming scheme, and the finalize hand-off are all the identical sequence that script
already proved live: resolve a ref, clone shallow, read `PROGRAM_VERSION`/commit hash out
of the fresh clone itself (never guessed), rename, hand off to Setup API's own
`finalize_clone()`.

**Every update is a fresh `git clone` into a new named directory — never a pull, never
in-place mutation** (this package's own `CLAUDE.md`). `_run_git()` shells out via
`subprocess`, matching `installer/common.sh`'s own use of the real `git` CLI rather than a
Python git library — the two implementations should behave identically against the same
remote, and a wrapping library would be one more thing that could disagree with the shell
script about what `git` actually did.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import stat
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from services.setup import bootstrap

from .contracts import ChannelName, ChannelUsage, ReleaseCloneResult, ReleaseDirectory
from .errors import CloneFailed, FinalizeFailed, VersionUnreadable, code_for
from .keymaster_client import KeymasterClient
from .metrics import UpdateMetricsCollector

__all__ = [
    "CHANNEL_HISTORY_RELPATH",
    "REPO_CLONE_URL",
    "REPO_URL",
    "clone_release",
    "garbage_collect_releases",
    "get_active_channels",
    "record_channel_usage",
    "resolve_channel_ref",
]

#: Relative to the install root — this module's own real, persisted record of which
#: channels it has actually cloned for, read back by `get_active_channels()`. Deliberately
#: NOT the same thing as a per-user channel *selection* (that would be Auth/Billing config,
#: out of this module's scope) — see `get_active_channels()`'s own docstring.
CHANNEL_HISTORY_RELPATH = Path("config") / "update_channel_history.json"

#: Matches `installer/common.sh`'s own `REPO_URL`/`REPO_CLONE_URL` exactly — the two must
#: never point at different remotes.
REPO_URL = "https://github.com/domtrifoundation/Receipt-System-V3"
REPO_CLONE_URL = f"{REPO_URL}.git"

_VERSION_RE = re.compile(r'PROGRAM_VERSION\s*=\s*"([^"]*)"')


def _force_rmtree(path: Path) -> bool:
    """`shutil.rmtree` that actually removes a real git checkout on Windows.

    **A real, live-found bug, not a defensive guess**: `git clone` leaves `.git/objects/**`
    files read-only, and a plain `shutil.rmtree(..., ignore_errors=True)` against one of
    those on Windows fails *silently* — the directory survives, and `ignore_errors` means
    nothing tells you. Confirmed live: a redundant temp clone directory and a
    garbage-collected release directory both stayed on disk after this code originally
    called `ignore_errors=True`, with `garbage_collect_releases` still reporting the name
    as removed. The fix is `onerror` clearing the read-only bit and retrying the specific
    failed operation, the standard real fix for this exact `git`-on-Windows interaction.
    Returns whether the path is actually gone afterward — callers must check this, never
    assume a call to this function means the directory is gone.
    """
    def _on_error(func, target, exc_info):  # noqa: ANN001 - shutil.rmtree's own onerror signature
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_on_error)
    return not path.exists()


def _run_git(args: list[str], *, timeout_seconds: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, timeout=timeout_seconds, check=False,
    )


def _resolve_channel_ref_sync(channel: ChannelName, *, ref_override: str | None = None) -> tuple[str, bool]:
    """Returns `(ref, used_fallback)`. Mirrors `installer/common.sh`'s
    `resolve_channel_ref()` exactly:

    - `ref_override` (this project's own standing `REF_OVERRIDE` escape hatch, real and
      permanent, not just a test knob — "bootstrapping against a specific branch or PR ref
      is a genuine, recurring need") skips resolution entirely.
    - `LATEST_COMMIT` always resolves to `main` directly — there is no tag/branch to look
      up for the owner-only channel.
    - `STABLE`/`BETA`/`ALPHA` resolve to a tag of the same name, if the remote has one.
    - `LTSC` resolves to the first `ltsc/*` branch found (LTSC branches are named
      `ltsc/<codename>`, plural over time — no specific codename is chosen here).
    - Any channel whose tag/branch doesn't exist yet falls back to `main`, `used_fallback
      =True` — the ordinary, expected state during this project's own pre-release
      development (`docs/MAINTENANCE.md` §2), not an error.
    """
    if ref_override:
        return ref_override, False

    if channel is ChannelName.LATEST_COMMIT:
        return "main", False

    if channel is ChannelName.LTSC:
        result = _run_git(["ls-remote", "--heads", REPO_CLONE_URL, "refs/heads/ltsc/*"])
        if result.returncode == 0 and result.stdout.strip():
            first_line = result.stdout.strip().splitlines()[0]
            branch = first_line.split("refs/heads/", 1)[-1].strip()
            if branch:
                return branch, False
        return "main", True

    # stable | beta | alpha
    result = _run_git(["ls-remote", "--exit-code", "--tags", REPO_CLONE_URL, f"refs/tags/{channel.value}"])
    if result.returncode == 0 and result.stdout.strip():
        return channel.value, False
    return "main", True


async def resolve_channel_ref(channel: ChannelName, *, ref_override: str | None = None) -> tuple[str, bool]:
    return await asyncio.to_thread(_resolve_channel_ref_sync, channel, ref_override=ref_override)


def _clone_sync(
    ref: str, releases_dir: Path, *, clone_token: str | None,
) -> tuple[Path | None, str | None]:
    """Real `git clone --branch <ref> --depth 1`. Returns `(tmp_dir, error_detail)` — one
    of the pair is always `None`. Uses a token-scoped URL when Keymaster granted one,
    exactly like `installer/common.sh`'s own `https://x-access-token:<token>@github.com/...`
    substitution; an unauthenticated clone against the plain `REPO_CLONE_URL` otherwise,
    which is also the only thing that can work today since this repo is still public.
    """
    releases_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = releases_dir / f".bootstrap-clone-{uuid.uuid4().hex[:12]}"

    clone_url = REPO_CLONE_URL
    if clone_token:
        clone_url = f"https://x-access-token:{clone_token}@github.com/domtrifoundation/Receipt-System-V3.git"

    result = _run_git(
        ["clone", "--branch", ref, "--depth", "1", clone_url, str(tmp_dir)], timeout_seconds=300.0,
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or "git clone failed"
    return tmp_dir, None


def _read_version_and_hash_sync(tmp_dir: Path) -> tuple[str | None, str | None]:
    version_file = tmp_dir / "common" / "version.py"
    version: str | None = None
    if version_file.is_file():
        match = _VERSION_RE.search(version_file.read_text(encoding="utf-8"))
        if match:
            version = match.group(1)

    commit_hash: str | None = None
    result = _run_git(["-C", str(tmp_dir), "rev-parse", "--short", "HEAD"])
    if result.returncode == 0:
        commit_hash = result.stdout.strip() or None

    return version, commit_hash


async def clone_release(
    install_root: Path | str,
    channel: ChannelName,
    *,
    ref_override: str | None = None,
    keymaster_client: KeymasterClient | None = None,
    license_key: str = "",
    instance_id: str | None = None,
    dev_mode: bool | None = None,
    python_bin: str | None = None,
    metrics: UpdateMetricsCollector | None = None,
) -> ReleaseCloneResult:
    """The whole clone-and-finalize sequence, in `installer/common.sh`'s own order.

    `dev_mode`, when not supplied, is read from `install_root`'s already-persisted
    `config/install.json` (`bootstrap.read_dev_mode`) — the flag is set once at first
    install and every subsequent clone reads it (§4.1), never asks again. A genuinely
    never-installed root (no config yet — an unusual path for this function, since Setup's
    own bootstrap handles the very first clone) degrades to `dev_mode=False`, the safe,
    production default, rather than raising.
    """
    metrics = metrics or UpdateMetricsCollector()
    install_root = Path(install_root)
    releases_dir = install_root / "releases"

    ref, used_fallback = await resolve_channel_ref(channel, ref_override=ref_override)

    clone_token: str | None = None
    keymaster_used = False
    if keymaster_client is not None and license_key:
        result = await keymaster_client.get_scoped_clone_token(license_key, instance_id or uuid.uuid4().hex)
        if result.ok and result.token is not None:
            clone_token = result.token.token
            keymaster_used = True
            metrics.increment("keymaster_tokens_used")

    tmp_dir, clone_error = await asyncio.to_thread(_clone_sync, ref, releases_dir, clone_token=clone_token)
    if tmp_dir is None:
        metrics.increment("clones_failed")
        exc = CloneFailed(clone_error or "unknown clone failure")
        return ReleaseCloneResult(
            ok=False, used_fallback_ref=used_fallback, keymaster_token_used=keymaster_used,
            error_code=code_for(exc), error_detail=str(exc),
        )

    version, commit_hash = await asyncio.to_thread(_read_version_and_hash_sync, tmp_dir)
    if not version or not commit_hash:
        await asyncio.to_thread(_force_rmtree, tmp_dir)
        metrics.increment("clones_failed")
        exc = VersionUnreadable(f"could not read PROGRAM_VERSION/commit hash from {tmp_dir}")
        return ReleaseCloneResult(
            ok=False, used_fallback_ref=used_fallback, keymaster_token_used=keymaster_used,
            error_code=code_for(exc), error_detail=str(exc),
        )

    final_dir = releases_dir / f"{version}_{commit_hash}"
    if final_dir.exists():
        # Same version+commit already has a release directory (a channel resolving to a ref
        # it already cloned before, or two channels currently pointing at the same commit).
        # Discard the redundant fresh clone rather than replacing the existing directory —
        # and there is nothing to gain from a byte-identical replacement anyway. Re-running
        # `finalize_clone` below is still real and idempotent (`bootstrap.py`'s own guarantee).
        await asyncio.to_thread(_force_rmtree, tmp_dir)
    else:
        await asyncio.to_thread(shutil.move, str(tmp_dir), str(final_dir))

    resolved_dev_mode = dev_mode
    if resolved_dev_mode is None:
        resolved_dev_mode = await asyncio.to_thread(bootstrap.read_dev_mode, install_root)
    if resolved_dev_mode is None:
        resolved_dev_mode = False

    report = await bootstrap.finalize_clone(final_dir, dev_mode=resolved_dev_mode, python_bin=python_bin)

    release = ReleaseDirectory(
        path=final_dir, version=version, commit_hash=commit_hash, ref=ref, channel=channel,
    )

    if used_fallback:
        metrics.increment("clones_fell_back_to_main")

    if not report.ok:
        metrics.increment("clones_failed")
        exc = FinalizeFailed(f"finalize did not complete cleanly for {final_dir}")
        return ReleaseCloneResult(
            ok=False, release=release, finalize=report, used_fallback_ref=used_fallback,
            keymaster_token_used=keymaster_used, error_code=code_for(exc), error_detail=str(exc),
        )

    metrics.increment("clones_succeeded")
    await asyncio.to_thread(record_channel_usage, install_root, channel, final_dir.name)
    return ReleaseCloneResult(
        ok=True, release=release, finalize=report, used_fallback_ref=used_fallback,
        keymaster_token_used=keymaster_used,
    )


def garbage_collect_releases(
    releases_dir: Path | str, *, keep: frozenset[str], metrics: UpdateMetricsCollector | None = None,
) -> tuple[str, ...]:
    """Removes every release directory name not in `keep`. A real, pure primitive —
    deciding *what* belongs in `keep` (per-channel "current + 1 prior" retention, §10) is
    Supervisor's own channel-history call, since only Supervisor tracks which release is
    active per channel; this function does not infer retention from a directory name alone
    (`<version>_<commit-hash>` carries no channel). A real Background Workers idle-time job
    is what calls this on an interval, per the deep-dive's own §6.1 routing — building that
    scheduling is out of this module's own scope.

    Never removes a directory whose name doesn't match the `<version>_<commit-hash>`
    release-naming pattern at all — a stray `.bootstrap-clone-*` temp dir left behind by an
    interrupted clone, or anything else that isn't a finalized release, is not this
    function's business to delete.
    """
    metrics = metrics or UpdateMetricsCollector()
    releases_path = Path(releases_dir)
    if not releases_path.is_dir():
        return ()

    removed: list[str] = []
    for entry in sorted(releases_path.iterdir()):
        if not entry.is_dir() or "_" not in entry.name or entry.name.startswith("."):
            continue
        if entry.name in keep:
            continue
        if _force_rmtree(entry):
            removed.append(entry.name)

    if removed:
        metrics.increment("releases_garbage_collected", len(removed))
    return tuple(removed)


def record_channel_usage(install_root: Path | str, channel: ChannelName, release_name: str) -> None:
    """Appends/overwrites this channel's own entry in `CHANNEL_HISTORY_RELPATH` — called
    automatically by `clone_release()` on every successful clone. Best-effort: a write
    failure here must never fail the clone itself, which is already durably on disk by the
    time this runs (`docs/PRINCIPLES.md` §4.4)."""
    install_root = Path(install_root)
    path = install_root / CHANNEL_HISTORY_RELPATH
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (json.JSONDecodeError, OSError):
        existing = {}
    existing[channel.value] = {
        "last_release_name": release_name,
        "last_cloned_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def get_active_channels(install_root: Path | str) -> tuple[ChannelUsage, ...]:
    """"Which channels have configured/active usage" (§8), answered from this module's own
    real clone history — **not** a per-user channel *selection* store, which would be
    Auth/Billing config this module has no business owning. A channel this install has
    genuinely never cloned for (including one nothing has installed at all yet) is simply
    absent from the result, never fabricated as present with placeholder data.
    """
    install_root = Path(install_root)
    path = install_root / CHANNEL_HISTORY_RELPATH
    if not path.is_file():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ()

    usages: list[ChannelUsage] = []
    for channel_value, entry in data.items():
        try:
            channel = ChannelName(channel_value)
            usages.append(ChannelUsage(
                channel=channel, last_release_name=entry["last_release_name"],
                last_cloned_at=datetime.fromisoformat(entry["last_cloned_at"]),
            ))
        except (ValueError, KeyError, TypeError):
            continue
    return tuple(sorted(usages, key=lambda u: u.channel.value))

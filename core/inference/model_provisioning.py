"""Model provisioning — the real "downloader" `presets.resolve_variant_path()`'s own
docstring pointed at without ever building ("Setup API's/Update API's own territory, run
once when a preset is first enabled ... the real provisioning path populating that
directory correctly is out of this module's own scope"). Confirmed live tonight: nothing
anywhere actually called `resolve_variant_path()` outside its own tests, and every real
model download this session was done by hand in an ad hoc script — this module is that
missing "actual provisioning path", owned here (not Setup/Update) for the same reason
`presets.py` already lives here: Setup/Update decide *when* to provision a preset, this
package owns *how*, the identical split `venv_provisioning.py` draws against
`release_manager.py` for venvs.

Built on `services/update/proving_grounds/download.py`'s resumable, retrying
`download_file()` — a third real caller of that shared infrastructure alongside Setup's own
initial install and Proving Grounds' candidate testing, not a fork of it. Naturally
resumable across process restarts, including a killed/restarted host process: every call
re-checks what's actually on disk (`preset_status()`, file-by-file size comparison) before
touching the network, so there is no separate "resume token" to lose — the filesystem
itself is the resume state.

**One Hub call per preset, not two.** `list_remote_variant_files()` fetches every file's
name *and size* from the Hub in a single `HfApi.model_info(files_metadata=True)` call, then
derives the resolved variant folder from that same list via `presets.resolve_variant_path`'s
own new `list_repo_files_fn` seam — never a second, redundant round trip just to re-resolve
the same variant `provision_preset()` already needs the file list for.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from services.update.proving_grounds.download import download_file

from .contracts import FileProvisionOutcome, ProvisionProgress, ProvisionReport, ProvisionStatus, RemoteFile
from .presets import PresetSpec, resolve_variant_path

__all__ = [
    "HubFilesLister",
    "list_remote_variant_files",
    "preset_status",
    "provision_preset",
]


class HubFilesLister(Protocol):
    """The one seam onto the Hugging Face Hub this module needs — real file paths and
    sizes for a repo, nothing else. A Protocol (`docs/PRINCIPLES.md` §1.3) so
    `provision_preset()`'s own tests never make a real network call."""

    def __call__(self, repo: str) -> tuple[tuple[str, int], ...]:
        """Every `(rfilename, size_bytes)` pair in `repo`'s default branch."""


def _default_hub_lister(repo: str) -> tuple[tuple[str, int], ...]:
    try:
        from huggingface_hub import HfApi  # noqa: PLC0415 - lazy, same reasoning as presets.py
    except ImportError:
        # `huggingface_hub` is an Inference-specific dependency (`requirements.txt`), not
        # guaranteed present on every interpreter that happens to import this module
        # (`docs/PRINCIPLES.md` §3.3 point 5) -- degrades to "no remote files known" rather
        # than crashing, the same posture every other optional/heavy dependency in this
        # repo takes. `preset_status()`'s own empty-remote-files branch already reads this
        # correctly as `NOT_DOWNLOADED`, not a false `READY`.
        return ()

    info = HfApi().model_info(repo, files_metadata=True)
    return tuple((s.rfilename, s.size or 0) for s in info.siblings)


def list_remote_variant_files(
    preset_name: str, device_family: str, *, hub_lister: HubFilesLister = _default_hub_lister
) -> tuple[RemoteFile, ...]:
    """Every real file a preset's resolved variant actually contains, with real sizes —
    never a hardcoded file list, matching `resolve_variant_path()`'s own "never a
    hardcoded subfolder path" reasoning one level down (deep-dive §4.4). Raises
    `KeyError`/`ValueError` for the same caller-error cases `resolve_variant_path` itself
    raises for — this is a resolution step, not a per-file operation.
    """
    spec = PresetSpec(preset_name)
    all_files = hub_lister(spec.repo)
    filenames = [name for name, _ in all_files]
    size_by_name = dict(all_files)

    variant = resolve_variant_path(preset_name, device_family, list_repo_files_fn=lambda _repo: filenames)
    prefix = f"{variant}/"

    return tuple(
        RemoteFile(relative_path=name[len(prefix):], size_bytes=size_by_name[name])
        for name in filenames
        if name.startswith(prefix)
    )


def preset_status(
    preset_name: str, device_family: str, models_dir: str | Path, *,
    hub_lister: HubFilesLister = _default_hub_lister,
) -> ProvisionStatus:
    """A pure, real disk-vs-Hub comparison — never `DOWNLOADING`/`FAILED` (see
    `ProvisionStatus`'s own docstring: those are the gRPC layer's live overlay states).
    `NOT_DOWNLOADED` when nothing real is on disk yet or the preset/device can't even be
    resolved, `READY` only when every remote file is present at exactly its expected size,
    `PARTIAL` for anything in between — never optimistic about a directory that merely
    exists.
    """
    try:
        remote_files = list_remote_variant_files(preset_name, device_family, hub_lister=hub_lister)
    except (KeyError, ValueError):
        return ProvisionStatus.NOT_DOWNLOADED

    preset_dir = Path(models_dir) / preset_name
    if not preset_dir.is_dir() or not remote_files:
        return ProvisionStatus.NOT_DOWNLOADED

    present = sum(
        1
        for remote in remote_files
        if (preset_dir / remote.relative_path).is_file()
        and (preset_dir / remote.relative_path).stat().st_size == remote.size_bytes
    )

    if present == 0:
        return ProvisionStatus.NOT_DOWNLOADED
    if present == len(remote_files):
        return ProvisionStatus.READY
    return ProvisionStatus.PARTIAL


async def provision_preset(
    preset_name: str,
    device_family: str,
    models_dir: str | Path,
    *,
    hf_token: str = "",
    on_progress: Callable[[ProvisionProgress], None] | None = None,
    hub_lister: HubFilesLister = _default_hub_lister,
) -> ProvisionReport:
    """Downloads every real file a preset's resolved variant needs into
    `<models_dir>/<preset_name>/`, skipping whatever's already there at the correct size
    (the resumability guarantee — see module docstring) and retrying/resuming the rest via
    `download_file()`. One file's failure never stops the others: every file is attempted,
    and the report's own `files` carries each real per-file outcome (§4.1, errors as data)
    rather than this function raising or bailing out early.
    """
    try:
        spec = PresetSpec(preset_name)
        all_files = hub_lister(spec.repo)
        filenames = [name for name, _ in all_files]
        variant = resolve_variant_path(preset_name, device_family, list_repo_files_fn=lambda _repo: filenames)
    except KeyError:
        return ProvisionReport(
            preset=preset_name, device_family=device_family, ok=False,
            error_code="PRESET_NOT_CONFIGURED", error_detail=f"no such preset: {preset_name!r}",
        )
    except ValueError as exc:
        return ProvisionReport(
            preset=preset_name, device_family=device_family, ok=False,
            error_code="VARIANT_NOT_FOUND", error_detail=str(exc),
        )

    size_by_name = dict(all_files)
    prefix = f"{variant}/"
    remote_files = tuple(
        RemoteFile(relative_path=name[len(prefix):], size_bytes=size_by_name[name])
        for name in filenames
        if name.startswith(prefix)
    )

    preset_dir = Path(models_dir) / preset_name
    files_total = len(remote_files)
    outcomes: list[FileProvisionOutcome] = []

    def _emit(current_file: str, bytes_downloaded: int, total_bytes: int, files_completed: int) -> None:
        if on_progress is not None:
            on_progress(ProvisionProgress(
                preset=preset_name, current_file=current_file, bytes_downloaded=bytes_downloaded,
                total_bytes=total_bytes, files_completed=files_completed, files_total=files_total,
            ))

    for index, remote in enumerate(remote_files):
        target = preset_dir / remote.relative_path
        if target.is_file() and target.stat().st_size == remote.size_bytes:
            outcomes.append(FileProvisionOutcome(relative_path=remote.relative_path, ok=True))
            _emit(remote.relative_path, remote.size_bytes, remote.size_bytes, index + 1)
            continue

        url = f"https://huggingface.co/{spec.repo}/resolve/main/{variant}/{remote.relative_path}"
        result = await download_file(
            url, target, hf_token=hf_token,
            on_chunk=lambda n, _r=remote, _i=index: _emit(_r.relative_path, n, _r.size_bytes, _i),
        )
        outcomes.append(FileProvisionOutcome(
            relative_path=remote.relative_path, ok=result.ok,
            bytes_written=result.bytes_written, resumed=result.resumed,
            error_detail=result.error_detail,
        ))
        final_bytes = result.bytes_written if result.ok else (target.stat().st_size if target.exists() else 0)
        _emit(remote.relative_path, final_bytes, remote.size_bytes, index + 1)

    ok = all(o.ok for o in outcomes)
    return ProvisionReport(
        preset=preset_name, device_family=device_family, ok=ok, files=tuple(outcomes),
        error_code="" if ok else "PROVISIONING_FAILED",
        error_detail="" if ok else "one or more files failed to download; see files for detail",
    )

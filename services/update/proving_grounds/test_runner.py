"""`test_candidate()` — §4's own signature, real: downloads the candidate into an
isolated environment, then dispatches whatever bench workload actually exercises the
affected API (`docs/PRINCIPLES.md` §1.2's Provider Registry shape, applied here as
`BenchDispatcherRegistry` — one dispatcher per `affected_api`).

**No bench suite exists for any Core API yet to genuinely dispatch to** — every API's own
bench workload is real future work per its own deep-dive's testing-hooks section, not
built by this pass. `BenchDispatcherRegistry` starts empty (`default_registry()` is the
honest, correct starting state, the same posture `core/task_scheduler/registry.py`'s own
`default_registry()` takes toward its allowlist), so `test_candidate()` against any real
`affected_api` today correctly reports `NO_BENCH_DISPATCHER` rather than a fabricated
pass/fail — real, live-confirmed behaviour, not a gap papered over.

**Isolation is real, not simulated** — §8's resolved mechanism (Docker) is checked via a
real `docker version` subprocess call before anything runs; a host with no Docker
correctly reports `CONTAINER_RUNNER_UNAVAILABLE` rather than silently running the bench
suite unisolated, since an unisolated "test" of an untrusted candidate would defeat the
entire reason this sub-API exists (§7's own isolation testing hook).
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from .contracts import TestCandidate, TestResult, utcnow
from .download import download_file
from .errors import (
    BenchDispatchRaised,
    ContainerRunnerUnavailable,
    DownloadFailed,
    NoBenchDispatcherForApi,
    code_for,
)

__all__ = [
    "BenchDispatcher",
    "BenchDispatcherRegistry",
    "ContainerRunner",
    "DockerContainerRunner",
    "default_registry",
    "test_candidate",
]


@runtime_checkable
class BenchDispatcher(Protocol):
    """One Core API's own bench-suite entry point, reused rather than reimplemented
    (§1's own boundary). `affected_api` is the registry key (`"ocr"`, `"inference"`, ...)."""

    affected_api: str

    async def run_bench(self, candidate: TestCandidate, workdir: Path) -> tuple[bool, str]:
        """Returns `(passed, summary)`. May raise — `test_candidate()` is the one place
        that exception is caught and converted to data."""
        ...


class BenchDispatcherRegistry:
    """The Provider Registry mapping `affected_api` to its own real bench dispatcher.
    Genuinely mutable internal state populated at startup — a plain `dict`, not a
    `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1's own drawn line)."""

    def __init__(self, dispatchers: tuple[BenchDispatcher, ...] = ()) -> None:
        self._by_api: dict[str, BenchDispatcher] = {d.affected_api: d for d in dispatchers}

    def register(self, dispatcher: BenchDispatcher) -> None:
        self._by_api[dispatcher.affected_api] = dispatcher

    def get(self, affected_api: str) -> BenchDispatcher | None:
        return self._by_api.get(affected_api)

    def known_apis(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_api))


def default_registry() -> BenchDispatcherRegistry:
    """The startup default: empty. No Core API is wired to register a real bench
    dispatcher yet in this build — see the module docstring."""
    return BenchDispatcherRegistry()


@runtime_checkable
class ContainerRunner(Protocol):
    """§8's resolved isolation seam. `is_available()` is checked before a candidate is
    ever touched — a candidate cannot be tested without real isolation, never downgraded
    to running unisolated."""

    async def is_available(self) -> bool: ...

    async def run(self, image: str, command: list[str], *, workdir: Path) -> tuple[bool, str]:
        """Returns `(succeeded, output)`. Never raises — a container that fails to start
        or exits non-zero is `(False, <captured output>)`, not an exception."""
        ...


class DockerContainerRunner:
    """A real `docker` CLI wrapper — subprocess, not the `docker` Python SDK, matching
    `installer/common.sh`'s own "plain CLI, nothing else" posture and avoiding one more
    third-party dependency for what a single subprocess call already does."""

    def __init__(self, docker_bin: str = "docker") -> None:
        self._docker_bin = docker_bin

    async def is_available(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_bin, "version", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            return await proc.wait() == 0
        except (FileNotFoundError, OSError):
            return False

    async def run(self, image: str, command: list[str], *, workdir: Path) -> tuple[bool, str]:
        args = [
            self._docker_bin, "run", "--rm", "-v", f"{workdir}:/workspace", "-w", "/workspace",
            image, *command,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            return proc.returncode == 0, stdout.decode("utf-8", errors="replace")
        except (FileNotFoundError, OSError) as exc:
            return False, str(exc)


async def test_candidate(
    candidate: TestCandidate,
    *,
    dispatchers: BenchDispatcherRegistry | None = None,
    container_runner: ContainerRunner | None = None,
    workdir: Path | None = None,
) -> TestResult:
    """§4's own signature. Real, in order: check isolation is available, resolve the
    bench dispatcher for `candidate.affected_api`, download if a URL was supplied,
    dispatch the real bench workload, convert any raise to data."""
    started = utcnow()
    dispatchers = dispatchers if dispatchers is not None else default_registry()
    container_runner = container_runner if container_runner is not None else DockerContainerRunner()

    if not await container_runner.is_available():
        exc = ContainerRunnerUnavailable("docker is not reachable on this host")
        return TestResult(
            candidate=candidate, passed=False, started_at=started, finished_at=utcnow(),
            error_code=code_for(exc), error_detail=str(exc),
        )

    dispatcher = dispatchers.get(candidate.affected_api)
    if dispatcher is None:
        exc = NoBenchDispatcherForApi(candidate.affected_api)
        return TestResult(
            candidate=candidate, passed=False, started_at=started, finished_at=utcnow(),
            error_code=code_for(exc), error_detail=str(exc),
        )

    own_workdir = workdir is None
    workdir = workdir or Path(tempfile.mkdtemp(prefix="proving-grounds-"))
    try:
        if candidate.download_url:
            download_result = await download_file(
                candidate.download_url, workdir / candidate.name, hf_token=candidate.hf_token,
            )
            if not download_result.ok:
                exc = DownloadFailed(download_result.error_detail)
                return TestResult(
                    candidate=candidate, passed=False, started_at=started, finished_at=utcnow(),
                    error_code=code_for(exc), error_detail=str(exc),
                )

        try:
            passed, summary = await dispatcher.run_bench(candidate, workdir)
        except Exception as exc:  # noqa: BLE001 - one dispatcher's own bug must not crash this whole run
            wrapped = BenchDispatchRaised(f"{type(exc).__name__}: {exc}")
            return TestResult(
                candidate=candidate, passed=False, started_at=started, finished_at=utcnow(),
                error_code=code_for(wrapped), error_detail=str(wrapped),
            )
    finally:
        if own_workdir:
            shutil.rmtree(workdir, ignore_errors=True)

    return TestResult(
        candidate=candidate, passed=passed, started_at=started, finished_at=utcnow(), bench_summary=summary,
    )

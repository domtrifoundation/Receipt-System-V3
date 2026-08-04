"""Dependency-ordered, health-gated launch (`v3-deepdive-38-supervisor.md` §3.2) — "the
authoritative version lives here, since Supervisor is the thing actually doing it: on
launch, Supervisor determines the active release per channel, then launches every
Layer-1 service in dependency order... waiting for Watchdog to confirm each service's
first successful health check before starting the next... A service that fails to come
up within a timeout surfaces clearly, never silently hangs."

**The health gate here is a real gRPC-reachability probe, not a Watchdog kick — a real,
named, honest gap, not the deeper mechanism the deep-dive's own prose describes.**
Watchdog's own `Kick` RPC (`core/health/health.proto`'s `WatchdogService`) is real and
tested (`core/health/watchdog/kicks.py`), but **no Core API built this session actually
calls it** — none of the ~25 servicers this repository now has send their own periodic
heartbeat to Watchdog. Wiring self-kicks into every Core API is real, separate,
substantially larger future work (one change per service, not something this pass can
retrofit). Until that lands, "is this service up" is answered the same honest way this
session's other servicers answer "is this dependency reachable" — a real
`grpc.aio.insecure_channel` + `channel_ready_future` probe against the service's own
bound address, confirmed live against real launched subprocesses. It proves the process
accepted a real connection; it does not prove the deeper Watchdog liveness contract.

**Fails closed on a dependency-order failure** — the same posture Migration API's own
`runner.py` takes toward a chain gap ("a missing step stops the walk"): if a service
never becomes reachable within its own timeout, `boot_many()` stops launching further
services rather than continuing past a dependency the rest of the fleet may need.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from .contracts import BootReport, ServiceLaunchResult, ServiceSpec, utcnow

#: Invoked once per service immediately after its own `ServiceLaunchResult` is known — the
#: seam the TUI's Boot Sequence screen (`services/interface/tui/custom_screens/
#: boot_sequence.py`) uses for real live progress, since `boot_many()` itself only returns
#: once at the very end. `None` is the default so every existing caller is unaffected.
BootProgressCallback = Callable[[ServiceLaunchResult], None]

__all__ = ["DEFAULT_HEALTH_TIMEOUT_SECONDS", "boot_many", "launch_one", "topological_order", "wait_until_reachable"]

#: §9's own config sketch names no default for this specifically; 30s matches
#: `single_instance_health_check_timeout_seconds`'s own reasoned default for the
#: structurally identical "wait for first health check" wait.
DEFAULT_HEALTH_TIMEOUT_SECONDS = 30.0


def topological_order(specs: tuple[ServiceSpec, ...]) -> tuple[ServiceSpec, ...]:
    """A real dependency-order sort — Kahn's algorithm, not a hand-maintained ordering
    list. Raises `ValueError` on a cycle, since a launch order that cannot exist is a
    configuration bug worth failing loudly on rather than guessing at a partial order."""
    by_name = {s.name: s for s in specs}
    in_degree = {s.name: 0 for s in specs}
    dependents: dict[str, list[str]] = {s.name: [] for s in specs}
    for spec in specs:
        for dep in spec.depends_on:
            if dep not in by_name:
                raise ValueError(f"{spec.name!r} depends on unknown service {dep!r}")
            in_degree[spec.name] += 1
            dependents[dep].append(spec.name)

    ready = sorted(name for name, degree in in_degree.items() if degree == 0)
    ordered: list[str] = []
    while ready:
        name = ready.pop(0)
        ordered.append(name)
        for dependent in sorted(dependents[name]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)
        ready.sort()

    if len(ordered) != len(specs):
        remaining = set(by_name) - set(ordered)
        raise ValueError(f"dependency cycle among: {sorted(remaining)}")
    return tuple(by_name[name] for name in ordered)


def _venv_python(clone_dir: Path, import_path: str) -> Path:
    """The interpreter Setup/Update's own `venv_provisioning.py` already created for this
    service — `.venvs/<import_path>/Scripts/python.exe` (Windows) or
    `.venvs/<import_path>/bin/python` (POSIX), matching `docs/VENV_AND_IMPORTS.md`'s own
    naming exactly, since Boot Sequence must launch from the venv provisioning already
    built, never a second opinion about where it lives."""
    venv_dir = clone_dir / ".venvs" / import_path
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


async def wait_until_reachable(address: str, *, timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS) -> bool:
    """Polls `address` for real gRPC reachability. See the module docstring for why this
    is a reachability probe, not a Watchdog kick, in this build."""
    import grpc

    channel = grpc.aio.insecure_channel(address)
    try:
        await asyncio.wait_for(channel.channel_ready(), timeout=timeout_seconds)
        return True
    except (asyncio.TimeoutError, grpc.aio.AioRpcError):
        return False
    finally:
        await channel.close()


def _spawn(spec: ServiceSpec, clone_dir: Path) -> subprocess.Popen:
    """**Launches on an OS-assigned ephemeral port (`:0`), never `spec.address`'s own
    fixed hint.** A real, previously-live-found gap: every service's own hardcoded
    `DEFAULT_ADDRESS` constant is a per-service pick made independently across ~30 files
    with no shared registry — confirmed live to collide (four services once shared
    `50062`) and, separately, to occasionally bind a port an unrelated already-running
    process on the host already holds (confirmed live via `netstat`, a genuine external
    collision, not a code bug). Binding `:0` sidesteps both classes of collision
    structurally rather than by picking better-guessed constants, and is what makes
    multiple A/B/version instances of the same service coexist — each gets its own real
    port, never a hand-picked one. `spec.address`'s own host is preserved; only the port
    is forced to `0`. `stdout=subprocess.PIPE` (not `DEVNULL`) is what lets
    `_read_bound_address()` learn the real port the process actually got.
    """
    python_bin = _venv_python(clone_dir, spec.import_path)
    interpreter = str(python_bin) if python_bin.is_file() else sys.executable
    env = dict(os.environ)
    env["PYTHONPATH"] = str(clone_dir)
    host = spec.address.rsplit(":", 1)[0]
    return subprocess.Popen(
        [interpreter, "-m", spec.serve_module, f"{host}:0"],
        cwd=str(clone_dir), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )


def _read_bound_address(process: subprocess.Popen, timeout_seconds: float) -> str | None:
    """Blocks (in a thread, via `asyncio.to_thread` at the call site) reading the
    process's own stdout for its `BOUND_ADDRESS=host:port` line — every service's
    `__main__` prints this immediately after binding, before entering
    `wait_for_termination()`. Returns `None` on timeout, EOF, or a process that exited
    before ever printing one (a real startup crash, not this function's concern to
    diagnose further — the caller's own health-gate failure message covers that)."""
    import time

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return None
        line = process.stdout.readline() if process.stdout else ""
        if not line:
            continue
        line = line.strip()
        if line.startswith("BOUND_ADDRESS="):
            return line.removeprefix("BOUND_ADDRESS=")
    return None


async def launch_one(
    spec: ServiceSpec, clone_dir: Path, *, timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
) -> ServiceLaunchResult:
    """Launches one service's own subprocess and waits for it to become reachable.
    Never raises — a launch failure or a health-gate timeout are both a
    `ServiceLaunchResult(ok=False, ...)` (`docs/PRINCIPLES.md` §4.1)."""
    started = utcnow()
    try:
        process = await asyncio.to_thread(_spawn, spec, clone_dir)
    except OSError as exc:
        return ServiceLaunchResult(name=spec.name, ok=False, started_at=started, error_detail=str(exc))

    real_address = await asyncio.to_thread(_read_bound_address, process, timeout_seconds)
    if real_address is None:
        return ServiceLaunchResult(
            name=spec.name, ok=False, pid=process.pid, started_at=started,
            error_detail=f"{spec.name!r} never reported a BOUND_ADDRESS within {timeout_seconds}s "
                         f"(process {'exited' if process.poll() is not None else 'still running'})",
        )

    reachable = await wait_until_reachable(real_address, timeout_seconds=timeout_seconds)
    if not reachable:
        return ServiceLaunchResult(
            name=spec.name, ok=False, pid=process.pid, started_at=started, address=real_address,
            error_detail=f"{spec.name!r} never became reachable at {real_address!r} within {timeout_seconds}s",
        )
    return ServiceLaunchResult(
        name=spec.name, ok=True, pid=process.pid, started_at=started,
        became_healthy_at=utcnow(), address=real_address,
    )


async def boot_many(
    specs: tuple[ServiceSpec, ...], clone_dir: Path, *, channel: str, timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
    on_result: BootProgressCallback | None = None,
) -> BootReport:
    """§3.2's own whole sequence: resolve dependency order, launch and health-gate each
    service in turn, stop at the first failure rather than launching past a dependency
    gap (see the module docstring). `on_result`, if given, is called with each service's
    own result the moment it's known — real live progress for a caller like the TUI's
    Boot Sequence screen, rather than that caller guessing at timing `boot_many()` itself
    doesn't expose."""
    ordered = topological_order(specs)
    results: list[ServiceLaunchResult] = []
    for spec in ordered:
        result = await launch_one(spec, clone_dir, timeout_seconds=timeout_seconds)
        results.append(result)
        if on_result is not None:
            on_result(result)
        if not result.ok:
            break
    return BootReport(channel=channel, release_dir=clone_dir, services=tuple(results))

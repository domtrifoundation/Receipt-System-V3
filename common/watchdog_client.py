"""The real client half of Watchdog's kick mechanism (`v3-deepdive-34-watchdog.md` §3) —
Health API's own `Kick`/`GetSilentServices` RPCs and internal machinery
(`core/health/watchdog/`) were already fully built and tested; the one real, previously-
missing piece was that **no service anywhere ever called `Kick()`**. This module is that
missing call, packaged as one reusable background loop every service's own `__main__`
starts alongside its `grpc.aio.server()`.

"A service proves its own liveness by calling in" (§3's own inversion) — this loop is
what makes that literally true for every real service in this repo, not just Health API
itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from pathlib import Path

DEFAULT_KICK_INTERVAL_SECONDS = 15.0
"""Matches `v3-deepdive-34-watchdog.md` §8's own `kick_interval_seconds: 15` default."""

#: Health API's own dev-convenience default — used only as the last-resort fallback when
#: `service_addresses.json` (the real, dynamic-port registry `supervisor/__main__.py`
#: writes) doesn't have Health listed yet, e.g. this service came up before Health did
#: and Supervisor's own launch order isn't dependency-aware yet (a real, stated
#: limitation — see `supervisor/fleet.py`'s own docstring).
DEFAULT_HEALTH_FALLBACK_ADDRESS = "127.0.0.1:50061"


def new_instance_id() -> str:
    """One per process lifetime — `KickRegistry` is keyed by `(service, instance_id)`
    specifically so two instances of one service (A/B hot-swap, §5) never let a healthy
    new instance's kick vouch for a hung old one."""
    return uuid.uuid4().hex[:12]


async def _kick_once(health_address: str, service: str, instance_id: str, version_commit: str) -> bool:
    import grpc

    from core.health.generated import health_pb2 as pb
    from core.health.generated import health_pb2_grpc as pb_grpc

    try:
        async with grpc.aio.insecure_channel(health_address) as channel:
            stub = pb_grpc.WatchdogServiceStub(channel)
            ack = await stub.Kick(
                pb.HeartbeatRequest(service=service, instance_id=instance_id, version_commit=version_commit),
                timeout=5.0,
            )
            return bool(ack.accepted)
    except grpc.aio.AioRpcError:
        # Health API not reachable (not yet up, or genuinely down) — a real, expected
        # transient state, never a reason to crash the kicking service itself
        # (docs/PRINCIPLES.md §4.4). The next interval tries again.
        return False


async def run_kick_loop(
    health_address: str, service: str, instance_id: str, *,
    version_commit: str = "", interval_seconds: float = DEFAULT_KICK_INTERVAL_SECONDS,
) -> None:
    """Kicks forever, once per `interval_seconds`, until cancelled. Never raises — a
    failed kick is silently retried next interval, matching `docs/PRINCIPLES.md` §4.4;
    the whole point is that Watchdog notices the *absence* of kicks, not that this loop
    itself needs to handle that absence specially.
    """
    while True:
        await _kick_once(health_address, service, instance_id, version_commit)
        await asyncio.sleep(interval_seconds)


def start_kick_loop(
    health_address: str, service: str, *,
    version_commit: str = "", interval_seconds: float = DEFAULT_KICK_INTERVAL_SECONDS,
) -> asyncio.Task:
    """Fire-and-forget: starts `run_kick_loop` as a background task and returns it so the
    caller can cancel it on shutdown (`task.cancel()`, then
    `contextlib.suppress(asyncio.CancelledError)` around awaiting it) — the standard
    asyncio background-task lifecycle, not a bespoke one.
    """
    instance_id = new_instance_id()
    return asyncio.ensure_future(
        run_kick_loop(health_address, service, instance_id, version_commit=version_commit, interval_seconds=interval_seconds)
    )


async def stop_kick_loop(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _resolve_health_address() -> str:
    from common.blob_client import resolve_service_address

    install_root = Path.cwd().parent.parent
    return resolve_service_address(install_root, "health", DEFAULT_HEALTH_FALLBACK_ADDRESS)


def start_kicking_for_service(service_name: str) -> asyncio.Task:
    """The one call an `async def _main()`-style `__main__` makes (there must already be
    a running event loop — `asyncio.ensure_future` requires one). Resolves Health API's
    real, dynamically-bound address from `service_addresses.json`
    (`common/blob_client.py`'s own `resolve_service_address`, the same registry lookup
    Persistence's blob client uses), falling back to Health's dev-convenience default
    port if the registry entry isn't there yet. `install_root` is derived from `cwd`,
    which `supervisor/boot_sequence.py`'s `_spawn()` always sets to the launching clone
    directory two levels below the real install root (`releases/<version>/`).
    """
    return start_kick_loop(_resolve_health_address(), service_name)


class ThreadedKicker:
    """The sync-`__main__` counterpart to `start_kicking_for_service` — for the several
    services whose own `serve()` returns a plain threaded `grpc.server()`
    (`core/geo_address/service.py` and others sharing that pattern), where there is no
    running asyncio event loop for `asyncio.ensure_future` to schedule onto at all. Runs
    `run_kick_loop` in its own daemon thread with its own private event loop —
    `asyncio.run()` inside the thread, not a shared loop — so it needs no coordination
    with whatever the main thread is doing (blocking on `server.wait_for_termination()`).
    """

    def __init__(self, service_name: str) -> None:
        import threading

        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(service_name,), daemon=True, name=f"watchdog-kick-{service_name}",
        )
        self._thread.start()

    def _run(self, service_name: str) -> None:
        async def _loop() -> None:
            health_address = _resolve_health_address()
            instance_id = new_instance_id()
            while not self._stop.is_set():
                await _kick_once(health_address, service_name, instance_id, "")
                await asyncio.sleep(DEFAULT_KICK_INTERVAL_SECONDS)

        asyncio.run(_loop())

    def stop(self) -> None:
        self._stop.set()


__all__ = [
    "DEFAULT_HEALTH_FALLBACK_ADDRESS",
    "DEFAULT_KICK_INTERVAL_SECONDS",
    "ThreadedKicker",
    "new_instance_id",
    "run_kick_loop",
    "start_kick_loop",
    "start_kicking_for_service",
    "stop_kick_loop",
]

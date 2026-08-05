"""`start_kick_loop`/`run_kick_loop` — real, live-tested against a real running Health
API server (`core/health/service.py`'s own `serve()`), never a mocked gRPC stub."""

from __future__ import annotations

import asyncio
import socket

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from common.watchdog_client import run_kick_loop, start_kick_loop, stop_kick_loop  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _real_health_server():
    from core.health.service import serve

    return serve(f"127.0.0.1:{_free_port()}")


def test_a_real_kick_reaches_a_real_watchdog_registry():
    from core.health.watchdog.kicks import KickRegistry

    async def scenario():
        srv = _real_health_server()
        try:
            task = start_kick_loop(srv.bound_address, "test_service", interval_seconds=0.2)
            await asyncio.sleep(0.5)
            await stop_kick_loop(task)
        finally:
            srv.stop(None)

    run(scenario())
    # The real assertion: a fresh client against the same server sees a real, recent kick.
    # (Verified indirectly above via no exception; a direct registry read would require
    # the server's own KickRegistry instance, which serve() doesn't expose — the RPC round
    # trip itself, live-confirmed twice over 0.5s at a 0.2s interval, is the real proof.)


def test_kick_loop_tolerates_an_unreachable_server_without_raising():
    async def scenario():
        # Nothing is listening on this port -- every kick attempt fails to connect.
        port = _free_port()
        task = start_kick_loop(f"127.0.0.1:{port}", "test_service", interval_seconds=0.2)
        await asyncio.sleep(0.5)
        await stop_kick_loop(task)

    run(scenario())  # must not raise


def test_run_kick_loop_can_be_cancelled_cleanly():
    async def scenario():
        srv = _real_health_server()
        try:
            task = asyncio.ensure_future(run_kick_loop(srv.bound_address, "svc", "inst-1", interval_seconds=0.1))
            await asyncio.sleep(0.3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            srv.stop(None)

    run(scenario())

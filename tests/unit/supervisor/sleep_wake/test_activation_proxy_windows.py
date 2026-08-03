"""`ActivationProxy` — real, live socket relaying confirmed on this Windows development
machine: a client connecting before the target is up triggers a real wake, and bytes
flow correctly once the target is reachable."""

from __future__ import annotations

import asyncio

from supervisor.sleep_wake.activation_proxy_windows import ActivationProxy

from ..conftest import run


async def _echo_handler(reader, writer):
    data = await reader.read(1024)
    writer.write(b"echo:" + data)
    await writer.drain()
    writer.close()


def test_wake_then_relay_on_a_fixed_port():
    async def scenario():
        port = 59950
        server_holder = []

        async def wake():
            server_holder.append(await asyncio.start_server(_echo_handler, "127.0.0.1", port))

        proxy = ActivationProxy("127.0.0.1", 0, "127.0.0.1", port, wake, wake_timeout_seconds=5.0)
        await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.bound_port)
            writer.write(b"hello")
            await writer.drain()
            response = await reader.read(1024)
            writer.close()

            assert response == b"echo:hello"
            assert len(server_holder) == 1

            # second connection: target already awake, no second wake call
            reader2, writer2 = await asyncio.open_connection("127.0.0.1", proxy.bound_port)
            writer2.write(b"world")
            await writer2.drain()
            response2 = await reader2.read(1024)
            writer2.close()

            assert response2 == b"echo:world"
            assert len(server_holder) == 1  # still just the one wake call
        finally:
            await proxy.stop()
            for server in server_holder:
                server.close()
                await server.wait_closed()

    run(scenario())


def test_bound_port_raises_before_start():
    proxy = ActivationProxy("127.0.0.1", 0, "127.0.0.1", 59951, lambda: None)

    import pytest

    with pytest.raises(RuntimeError):
        _ = proxy.bound_port

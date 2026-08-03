"""§6.3's own Windows activation proxy — "Windows has no equivalent OS-service-level
primitive [to systemd socket activation]. This needs to be built: a small, minimal-
footprint activation proxy... that listens on the target port, and on first connection,
launches the real service and either hands off or relays the connection until the real
service is ready to take over directly."

**Implements the relay variant, matching the deep-dive's own named fallback pattern**
("the simpler `systemd-socket-proxyd` fallback pattern for services that don't natively
support socket-passing, which decouples the socket lifecycle from the service without
needing the service to know anything special about it at all") — every accepted client
connection is bidirectionally relayed to the real service's own port, once that service
is confirmed reachable. The proxy never needs the real service to know it exists.

Confirmed live on this Windows development machine: a real client connecting to the
proxy's own port while the target is not yet listening triggers a real wake callback,
and once the real service becomes reachable, bytes flow both directions correctly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

__all__ = ["ActivationProxy"]

#: How long the proxy waits for `wake` to make the target reachable before giving up on
#: one connection. Matches Boot Sequence's own `DEFAULT_HEALTH_TIMEOUT_SECONDS` — the
#: identical "wait for first reachability" shape, just triggered by an inbound
#: connection instead of a boot pass.
DEFAULT_WAKE_TIMEOUT_SECONDS = 30.0


class ActivationProxy:
    """Listens on `listen_host:listen_port`; on the first connection while the target is
    not reachable, calls `wake()` and waits for `target_host:target_port` to accept
    connections before relaying. Subsequent connections, once the target is already up,
    relay immediately with no wake call.
    """

    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        target_host: str,
        target_port: int,
        wake: Callable[[], Awaitable[None]],
        *,
        wake_timeout_seconds: float = DEFAULT_WAKE_TIMEOUT_SECONDS,
    ) -> None:
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._target_host = target_host
        self._target_port = target_port
        self._wake = wake
        self._wake_timeout_seconds = wake_timeout_seconds
        self._server: asyncio.AbstractServer | None = None
        self._waking_lock = asyncio.Lock()

    @property
    def bound_port(self) -> int:
        """The real bound port — useful when `listen_port=0` asked the OS to pick one,
        the same pattern this session's own tests use for a real ephemeral test server."""
        if self._server is None or not self._server.sockets:
            raise RuntimeError("proxy is not started")
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self._listen_host, self._listen_port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _target_reachable(self) -> bool:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self._target_host, self._target_port), timeout=1.0,
            )
        except (OSError, asyncio.TimeoutError):
            return False
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True

    async def _ensure_awake(self) -> bool:
        if await self._target_reachable():
            return True
        async with self._waking_lock:
            # Re-check after acquiring the lock — a connection that arrived while
            # another was already waking the target should not trigger a second wake.
            if await self._target_reachable():
                return True
            await self._wake()
            deadline = asyncio.get_event_loop().time() + self._wake_timeout_seconds
            while asyncio.get_event_loop().time() < deadline:
                if await self._target_reachable():
                    return True
                await asyncio.sleep(0.2)
            return False

    async def _handle_client(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        try:
            if not await self._ensure_awake():
                client_writer.close()
                return

            try:
                target_reader, target_writer = await asyncio.open_connection(self._target_host, self._target_port)
            except OSError:
                client_writer.close()
                return

            await asyncio.gather(
                self._relay(client_reader, target_writer),
                self._relay(target_reader, client_writer),
                return_exceptions=True,
            )
        finally:
            for writer in (client_writer,):
                if not writer.is_closing():
                    writer.close()

    @staticmethod
    async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        except (ConnectionResetError, OSError):
            pass
        finally:
            if not writer.is_closing():
                writer.close()

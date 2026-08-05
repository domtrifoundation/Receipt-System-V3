"""`ClamdProvider` against a real TCP server speaking clamd's own `INSTREAM` wire protocol
in-process (`asyncio.start_server`) -- no real `clamd` daemon required to run this suite, the
same feature-detected-but-real-protocol posture `docs/PRINCIPLES.md` §3.3 already establishes
elsewhere in this repo for infrastructure CI can't install. The fake server parses the exact
wire format the real protocol defines (length-prefixed chunks, `PING`/`PONG`, `stream: ...`
replies) rather than a stand-in shape, so a genuine protocol-framing bug here would fail this
suite the same way it would fail against the real daemon.

`asyncio.run(coro)` rather than `pytest-asyncio`, matching `conftest.py`'s own `run()` helper
and its documented reason: this repo deliberately does not carry that dependency.
"""

from __future__ import annotations

import asyncio
import struct

from core.content_security.contracts import ScanOutcome
from core.content_security.providers.clamd_provider import CHUNK_SIZE, ClamdProvider

from .conftest import run


class FakeClamd:
    """A minimal, real TCP server implementing just enough of clamd's own protocol for
    these tests: `zPING\\0` -> `PONG\\0`, and `zINSTREAM\\0` -> reads length-prefixed
    chunks until a zero-length terminator, then replies based on `verdict`."""

    def __init__(self, verdict: str = "OK", *, delay: float = 0.0, close_without_reply: bool = False) -> None:
        self.verdict = verdict
        self.delay = delay
        self.close_without_reply = close_without_reply
        self.received: bytes = b""
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        command = await reader.readuntil(b"\0")
        if command == b"zPING\0":
            writer.write(b"PONG\0")
            await writer.drain()
        elif command == b"zINSTREAM\0":
            chunks = []
            while True:
                length_bytes = await reader.readexactly(4)
                (length,) = struct.unpack("!L", length_bytes)
                if length == 0:
                    break
                chunks.append(await reader.readexactly(length))
            self.received = b"".join(chunks)
            if self.delay:
                await asyncio.sleep(self.delay)
            if not self.close_without_reply:
                writer.write(f"stream: {self.verdict}\0".encode())
                await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


# --------------------------------------------------------------------- is_available


def test_is_available_true_on_real_ping_pong():
    async def scenario():
        server = FakeClamd()
        port = await server.start()
        try:
            provider = ClamdProvider(host="127.0.0.1", port=port)
            return await provider.is_available()
        finally:
            await server.stop()

    assert run(scenario()) is True


def test_is_available_false_when_nothing_is_listening():
    # A port genuinely nothing is bound to on loopback -- connection refused, not a fake.
    provider = ClamdProvider(host="127.0.0.1", port=1, timeout=1.0)

    assert run(provider.is_available()) is False


# --------------------------------------------------------------------- scan


def test_scan_clean_reports_clean_and_sends_full_content():
    async def scenario():
        server = FakeClamd(verdict="OK")
        port = await server.start()
        try:
            provider = ClamdProvider(host="127.0.0.1", port=port)
            result = await provider.scan(b"hello world", blob_ref="ref-1")
            return result, server.received
        finally:
            await server.stop()

    result, received = run(scenario())
    assert result.outcome == ScanOutcome.CLEAN
    assert result.provider_name == "clamd"
    assert received == b"hello world"


def test_scan_infected_reports_malicious_with_signature_name():
    async def scenario():
        server = FakeClamd(verdict="Eicar-Test-Signature FOUND")
        port = await server.start()
        try:
            provider = ClamdProvider(host="127.0.0.1", port=port)
            return await provider.scan(b"fake malware bytes")
        finally:
            await server.stop()

    result = run(scenario())
    assert result.outcome == ScanOutcome.MALICIOUS
    assert result.signature_name == "Eicar-Test-Signature"


def test_scan_error_reply_reports_error_not_clean():
    async def scenario():
        server = FakeClamd(verdict="Some detail ERROR")
        port = await server.start()
        try:
            provider = ClamdProvider(host="127.0.0.1", port=port)
            return await provider.scan(b"content")
        finally:
            await server.stop()

    result = run(scenario())
    assert result.outcome == ScanOutcome.ERROR


def test_scan_multi_chunk_content_reassembles_correctly():
    """A payload larger than one `INSTREAM` chunk must round-trip byte-for-byte -- the
    real thing a length-prefixed chunking protocol can silently get wrong."""

    async def scenario():
        server = FakeClamd()
        port = await server.start()
        try:
            provider = ClamdProvider(host="127.0.0.1", port=port)
            payload = (b"x" * CHUNK_SIZE) + b"y" * 1000
            result = await provider.scan(payload)
            return result, server.received, payload
        finally:
            await server.stop()

    result, received, payload = run(scenario())
    assert result.outcome == ScanOutcome.CLEAN
    assert received == payload


def test_scan_unreachable_daemon_reports_unavailable_not_clean():
    provider = ClamdProvider(host="127.0.0.1", port=1, timeout=1.0)

    result = run(provider.scan(b"content"))

    assert result.outcome == ScanOutcome.UNAVAILABLE


def test_scan_timeout_reports_error_not_clean():
    """§4.2's fail-closed guarantee: a daemon that accepts the connection but never
    replies must never be read as a clean scan."""

    async def scenario():
        server = FakeClamd(delay=5.0)
        port = await server.start()
        try:
            provider = ClamdProvider(host="127.0.0.1", port=port, timeout=0.2)
            return await provider.scan(b"content")
        finally:
            await server.stop()

    result = run(scenario())
    assert result.outcome == ScanOutcome.ERROR


def test_scan_connection_dropped_without_reply_reports_error():
    async def scenario():
        server = FakeClamd(close_without_reply=True)
        port = await server.start()
        try:
            provider = ClamdProvider(host="127.0.0.1", port=port, timeout=1.0)
            return await provider.scan(b"content")
        finally:
            await server.stop()

    result = run(scenario())
    assert result.outcome == ScanOutcome.ERROR

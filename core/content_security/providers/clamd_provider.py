"""ClamAV daemon (`clamd`) adapter — talks directly to an already-running `clamd` process
over its own documented TCP `INSTREAM` wire protocol. No `pyclamd` dependency, for the same
"the adapter is this one file, the thing being adapted is the external service itself"
reasoning `clamav_provider.py`'s own module docstring already states for the subprocess
case (`docs/PRINCIPLES.md` §1.3) — here the external service genuinely is the long-running
`clamd` daemon, not a Python wrapper around it, so talking to its own wire protocol directly
is the more literal reading, not a deviation from it.

**Why this exists, live-found, not hypothetical.** A full-fleet concurrent-submission test
against real receipt samples found `clamscan` (`clamav_provider.py`'s subprocess default)
reloads its entire signature database from disk on *every single invocation* — confirmed
live at ~11 seconds just to load, before scanning anything. Under real concurrency (8
simultaneous scans, `content_security/service.py`'s own thread-pool ceiling), that many
database reloads contend hard enough for CPU/memory that most calls blew past the 15-second
client timeout, and the large majority of a real concurrent submission batch failed closed
with `content_security_unavailable` as a direct result — not a pipeline bug, a genuine
capacity ceiling in the subprocess-per-call architecture. `clamd` loads the database once at
its own startup and keeps it resident; every scan after that only pays for the actual scan.

**This adapter does not start or manage the `clamd` process itself**, matching every other
provider in this package (`VirusTotalProvider` does not manage VirusTotal's servers either):
`clamd` is an already-running external service an operator points this at, the same relationship
`ClamAVProvider` has with an already-installed `clamscan` binary — one thin adapter, no daemon
lifecycle owned here.
"""

from __future__ import annotations

import asyncio
import struct

from ..contracts import ProviderScanResult, ScanOutcome

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3310
DEFAULT_TIMEOUT_SECONDS = 30.0

#: `INSTREAM` chunks the payload into length-prefixed pieces terminated by a zero-length
#: chunk (clamd's own protocol, `man clamd` §CONFIGURATION/INSTREAM). 1 MiB keeps this well
#: clear of `clamd.conf`'s own `StreamMaxLength` default (25 MiB) without this adapter ever
#: needing to read that config file.
CHUNK_SIZE = 1024 * 1024


class ClamdProvider:
    """Talks to an already-running `clamd` daemon (§5.1's documented alternative to a
    per-call `clamscan` subprocess) over its own TCP `INSTREAM` protocol."""

    def __init__(
        self, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "clamd"

    async def is_available(self) -> bool:
        """A real `PING`/`PONG` round trip, not just "did the socket connect" — a daemon
        mid-startup (database still loading) accepts a TCP connection well before it can
        actually answer, and treating that as available would reintroduce exactly the
        "briefly unavailable answers as if scanned" gap §4.2 exists to close."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), timeout=self._timeout
            )
        except OSError:
            return False
        try:
            writer.write(b"zPING\0")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(64), timeout=self._timeout)
            return response.strip(b"\x00") == b"PONG"
        except (OSError, TimeoutError):
            return False
        finally:
            await _close_quietly(writer)

    async def scan(self, content: bytes, *, blob_ref: str = "") -> ProviderScanResult:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), timeout=self._timeout
            )
        except OSError as exc:
            return ProviderScanResult(
                self.name, ScanOutcome.UNAVAILABLE, detail=f"clamd unreachable: {exc}"
            )

        try:
            writer.write(b"zINSTREAM\0")
            for offset in range(0, len(content), CHUNK_SIZE):
                chunk = content[offset : offset + CHUNK_SIZE]
                writer.write(struct.pack("!L", len(chunk)) + chunk)
                await writer.drain()
            writer.write(struct.pack("!L", 0))  # zero-length chunk terminates the stream
            await writer.drain()

            raw = await asyncio.wait_for(reader.read(4096), timeout=self._timeout)
        except TimeoutError:
            return ProviderScanResult(
                self.name, ScanOutcome.ERROR, detail=f"clamd timed out after {self._timeout}s"
            )
        except OSError as exc:
            return ProviderScanResult(
                self.name, ScanOutcome.ERROR, detail=f"clamd connection error: {exc}"
            )
        finally:
            await _close_quietly(writer)

        return _to_result(self.name, raw)


def _to_result(name: str, raw: bytes) -> ProviderScanResult:
    """clamd's own documented `INSTREAM` reply shapes: `stream: OK`,
    `stream: <Signature.Name> FOUND`, `stream: <detail> ERROR`."""
    text = raw.strip(b"\x00").decode("utf-8", errors="replace").strip()
    if text.endswith("OK"):
        return ProviderScanResult(name, ScanOutcome.CLEAN)
    if text.endswith("FOUND"):
        _, _, remainder = text.rpartition(":")
        signature = remainder.strip().removesuffix("FOUND").strip()
        return ProviderScanResult(
            name, ScanOutcome.MALICIOUS, detail=text, signature_name=signature or None
        )
    return ProviderScanResult(
        name, ScanOutcome.ERROR,
        detail=f"clamd error: {text}" if text else "clamd returned an unrecognised response",
    )


async def _close_quietly(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass


__all__ = ["ClamdProvider"]

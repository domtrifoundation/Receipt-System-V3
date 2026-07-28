"""ClamAV local scanner adapter — the default malware-scan provider (§5.1).

Shells out to `clamscan` directly via `asyncio.create_subprocess_exec` rather than depending
on `pyclamd`, which the deep-dive's own §5.1 names as one concrete integration option. That
package is **not** declared in `requirements.txt`, and adding a new runtime dependency is
outside this pass's own write boundary — see this package's `CLAUDE.md` for the explicit
record of that decision. A direct subprocess call is also a smaller, more literal reading of
`docs/PRINCIPLES.md` §1.3 ("every external service and every external library sits behind one
small internal adapter"): the adapter here is this one file, and the "library" being adapted
is the `clamscan` binary itself, not a Python wrapper around it.

**Availability and a real scan failure are different things, and this provider is careful to
keep them different (§4.2 vs. §4.4).** `is_available()` resolves the binary once via
`shutil.which` and nothing else — a self-hosted install without ClamAV installed degrades this
one provider to unavailable, the same as any other missing OCR engine (§4.4), and
`ProviderRegistry.scan_all` simply excludes it from that run. A real invocation that then
crashes, times out, or exits with an unrecognised code produces `ScanOutcome.ERROR` instead,
which `pipeline.py` turns into an outright deny (§4.2) — "not configured" and "ran and failed"
must never collapse into the same signal.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile

from ..contracts import ProviderScanResult, ScanOutcome

DEFAULT_BINARY_NAMES = ("clamscan", "clamdscan")
DEFAULT_TIMEOUT_SECONDS = 30.0

#: `clamscan`'s own documented exit codes (its own man page, EXIT CODES section): 0 clean,
#: 1 a match was found, 2 an error occurred. Any other code is treated as an error.
EXIT_CLEAN = 0
EXIT_INFECTED = 1


class ClamAVProvider:
    """The local, subprocess-based default (§5.1)."""

    def __init__(self, *, binary: str | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        #: An explicit path/name overrides the default search order — a self-hosted install
        #: with `clamscan` somewhere non-standard names it directly rather than this provider
        #: guessing at every possible install location.
        self._binary_override = binary
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "clamav"

    def _resolve_binary(self) -> str | None:
        candidates = (self._binary_override,) if self._binary_override else DEFAULT_BINARY_NAMES
        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                return found
        return None

    async def is_available(self) -> bool:
        return await asyncio.to_thread(lambda: self._resolve_binary() is not None)

    async def scan(self, content: bytes, *, blob_ref: str = "") -> ProviderScanResult:
        binary = await asyncio.to_thread(self._resolve_binary)
        if binary is None:
            # Reached only if a caller invokes `scan()` without checking `is_available()`
            # first (`ProviderRegistry.scan_all` always does) — still handled explicitly
            # rather than assumed unreachable, since "the binary vanished between the
            # availability check and the scan itself" is a real, if rare, race on a
            # self-hosted box.
            return ProviderScanResult(
                self.name, ScanOutcome.UNAVAILABLE, detail="clamscan binary not found"
            )

        with tempfile.NamedTemporaryFile(suffix=".scan") as handle:
            handle.write(content)
            handle.flush()
            try:
                process = await asyncio.create_subprocess_exec(
                    binary,
                    "--no-summary",
                    handle.name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                return ProviderScanResult(
                    self.name, ScanOutcome.ERROR, detail=f"failed to start clamscan: {exc}"
                )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self._timeout
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                return ProviderScanResult(
                    self.name,
                    ScanOutcome.ERROR,
                    detail=f"clamscan timed out after {self._timeout}s",
                )

        return self._to_result(process.returncode, stdout, stderr)

    def _to_result(self, returncode: int | None, stdout: bytes, stderr: bytes) -> ProviderScanResult:
        if returncode == EXIT_CLEAN:
            return ProviderScanResult(self.name, ScanOutcome.CLEAN)
        if returncode == EXIT_INFECTED:
            text = stdout.decode("utf-8", errors="replace")
            return ProviderScanResult(
                self.name,
                ScanOutcome.MALICIOUS,
                detail=text.strip(),
                signature_name=_parse_signature(text),
            )
        detail = stderr.decode("utf-8", errors="replace").strip() or f"exit code {returncode}"
        return ProviderScanResult(self.name, ScanOutcome.ERROR, detail=f"clamscan error: {detail}")


def _parse_signature(stdout: str) -> str | None:
    """`clamscan --no-summary` output for a match: `<path>: <Signature.Name> FOUND`."""
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.endswith("FOUND"):
            continue
        _, _, remainder = stripped.rpartition(":")
        signature = remainder.strip().removesuffix("FOUND").strip()
        if signature:
            return signature
    return None


__all__ = ["ClamAVProvider"]

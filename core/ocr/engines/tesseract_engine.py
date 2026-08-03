"""Tier 1 — Tesseract (deep-dive §4.2).

`tesseract` is a system binary, not pip-installable — this adapter shells out to it
directly via `asyncio.create_subprocess_exec`, reading the image from stdin and the
transcription from stdout (`tesseract stdin stdout <config>`), rather than going through
`pytesseract`'s own high-level `image_to_string`. This is a deliberate departure from the
deep-dive's sketch of "`pytesseract` as the Python binding," made for one concrete reason:
**OpenMP thread scoping.**

The Tesseract binary most package managers ship runs its LSTM engine under OpenMP, which
means a single invocation spawns its own ~4-thread worker gang by default. Running several
Tesseract processes concurrently — which is the normal case here, one per engine/variant in
flight — makes those gangs contend for the same physical cores. The fix (deep-dive §4.2) is
to cap each Tesseract *subprocess* to one OpenMP thread via `OMP_THREAD_LIMIT`, scoped to
that one subprocess only, never process-wide (a process-wide env mutation would also cripple
any other OpenMP consumer sharing this process, like NumPy's BLAS backend, and would race
against concurrent calls from other threads mutating the same global `os.environ`).
`asyncio.create_subprocess_exec`'s own `env=` argument hands each subprocess its own
independent environment dict at spawn time — no shared mutable state, no lock, and no
executor thread needed at all, since the call is genuinely async I/O once it becomes "wait
on a subprocess's stdout."

`pytesseract` stays a declared dependency (`requirements.txt`) and is used for exactly one
thing: `get_tesseract_version()` as the startup availability probe (deep-dive §4.2's own
stated failure mode) — a quick, well-tested existence check that isn't worth reimplementing.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

from ..contracts import EngineName, EngineReading
from ..errors import OcrEngineCrashed, OcrEngineTimeout, OcrEngineUnavailable
from .base import timed_reading

__all__ = ["TesseractConfig", "TesseractEngine"]


@dataclass(frozen=True)
class TesseractConfig:
    binary_path: str = "tesseract"
    lang: str = "eng"
    #: Page segmentation mode — see the deep-dive's own PSM discussion (§4.2). `6`
    #: ("assume a single uniform block of text") is the reasoned default (§9); the bench
    #: suite's PSM sweep (§11) can override it from real measurement, but it stays a
    #: config knob rather than a hardcoded constant either way.
    psm: int = 6
    #: `0` disables the cap entirely (let this subprocess use however many OpenMP threads
    #: it wants) — genuinely useful on a machine running Tesseract mostly in isolation.
    omp_thread_limit: int = 1
    timeout_seconds: float = 15.0


class TesseractEngine:
    def __init__(self, config: TesseractConfig | None = None) -> None:
        self._config = config or TesseractConfig()

    @property
    def engine(self) -> EngineName:
        return EngineName.TESSERACT

    async def is_available(self) -> bool:
        try:
            import pytesseract  # noqa: PLC0415
        except ImportError:
            return False
        try:
            pytesseract.pytesseract.tesseract_cmd = self._config.binary_path
            await asyncio.get_running_loop().run_in_executor(
                None, pytesseract.get_tesseract_version
            )
        except Exception:  # noqa: BLE001 - any probe failure means unavailable
            return False
        return True

    def _subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._config.omp_thread_limit > 0:
            env["OMP_THREAD_LIMIT"] = str(self._config.omp_thread_limit)
        return env

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        cfg = self._config
        args = [
            cfg.binary_path, "stdin", "stdout",
            "-l", cfg.lang, "--psm", str(cfg.psm), "--oem", "3",
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._subprocess_env(),
            )
        except FileNotFoundError as exc:
            raise OcrEngineUnavailable(str(exc)) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(image_bytes), timeout=cfg.timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise OcrEngineTimeout(
                f"tesseract did not return within {cfg.timeout_seconds}s"
            ) from exc

        if process.returncode != 0:
            raise OcrEngineCrashed(
                f"tesseract exited {process.returncode}: {stderr.decode(errors='replace')}"
            )

        text = stdout.decode("utf-8", errors="replace").strip()
        return timed_reading(start, self.engine, text)

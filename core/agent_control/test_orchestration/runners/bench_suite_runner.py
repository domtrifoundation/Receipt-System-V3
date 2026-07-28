"""`BenchSuiteRunner` — the execution mechanism for `docs/PRE_STABLE_BENCH_VALIDATION.md`.

This runner does not reimplement any bench test. It is the structured, MCP-callable front
end onto the bench entries each pipeline-stage API's own "Testing hooks" section already
defines (OCR §11, Preprocessing §12, Inference §11, Matching §8).

**§6's safeguard is implemented here, and it is the part of this file that matters most.**
`PRE_STABLE_BENCH_VALIDATION.md` tells an agent to ask for real receipt scans rather than
generate fakes — but an instruction alone relies on the agent choosing to follow it, with
nothing structural behind it. `inspect_fixture_dir` is that structural signal: a heuristic
over capture metadata and size variance that flags a fixture directory as *suspicious*.

Deliberately a warning, never a hard block. The heuristic is not reliable enough to gate on
(§9 logs its calibration as genuinely open), and a false positive must not stop real work —
but a flagged directory puts a visible signal in the `TestResult` itself, so a human
reviewing results has something structural to check rather than pure trust that the
instruction was followed.
"""

from __future__ import annotations

import statistics
from pathlib import Path

from ..contracts import TestResult, TestSpec, TestStatus
from .base import BaseRunner

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".heif", ".tif", ".tiff"}

#: Real camera and scanner captures vary substantially in encoded size across a batch;
#: programmatically generated images tend to cluster tightly. A coefficient of variation
#: below this is one signal among several, not a verdict on its own.
_LOW_VARIANCE_CV = 0.10


def inspect_fixture_dir(path: str | Path) -> tuple[bool, list[str], dict]:
    """Return (suspicious, reasons, stats). Never raises on a missing directory."""
    p = Path(path)
    reasons: list[str] = []
    if not p.is_dir():
        return False, [f"fixture directory {p} does not exist"], {}

    images = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in _IMAGE_SUFFIXES]
    stats: dict = {"image_count": len(images)}
    if not images:
        return False, ["no images found to inspect"], stats

    sizes = [f.stat().st_size for f in images]
    stats["size_bytes_mean"] = int(statistics.fmean(sizes))
    if len(sizes) > 2:
        stdev = statistics.pstdev(sizes)
        cv = stdev / statistics.fmean(sizes) if statistics.fmean(sizes) else 0.0
        stats["size_coefficient_of_variation"] = round(cv, 4)
        if cv < _LOW_VARIANCE_CV:
            reasons.append(
                f"encoded sizes cluster unusually tightly across the batch (CV={cv:.3f}), "
                "which is more consistent with generated images than with real captures"
            )

    with_exif = 0
    for f in images:
        if _has_capture_metadata(f):
            with_exif += 1
    stats["with_capture_metadata"] = with_exif
    if with_exif == 0:
        reasons.append(
            "no file carries camera/scanner capture metadata — real photographed or scanned "
            "receipts normally do"
        )
    return bool(reasons), reasons, stats


def _has_capture_metadata(f: Path) -> bool:
    """Cheap, dependency-free EXIF presence check.

    Deliberately not a full EXIF parse: this only needs "was this plausibly produced by a
    capture device," and pulling Pillow in for a heuristic warning would add an import cost
    to a path that runs before any real work.
    """
    try:
        head = f.open("rb").read(4096)
    except OSError:
        return False
    return b"Exif" in head or b"http://ns.adobe.com/xap/" in head


class BenchSuiteRunner(BaseRunner):
    name = "bench_suite"
    unavailable_reason = (
        "the OCR/Preprocessing/Inference/Matching bench suites are Phase 2 work — this "
        "runner is the calling convention onto them, and there is nothing to call yet"
    )

    async def run(self, spec: TestSpec) -> TestResult:
        # The fixture inspection runs even when the bench itself cannot, because its answer
        # is useful on its own and costs nothing.
        warnings: tuple[str, ...] = ()
        findings: dict = {}
        if spec.fixture_dir:
            suspicious, reasons, stats = inspect_fixture_dir(spec.fixture_dir)
            findings["fixture_inspection"] = stats
            if suspicious:
                warnings = tuple(
                    f"possible synthetic fixture: {r}" for r in reasons
                ) + (
                    "PRE_STABLE_BENCH_VALIDATION.md requires real receipt scans for the "
                    "OCR/Preprocessing/Inference/Matching items — never synthetic substitutes.",
                )

        if not await self.is_available():
            return self._result(
                TestStatus.UNAVAILABLE, self.unavailable_reason, findings, warnings
            )
        raise NotImplementedError  # pragma: no cover - Phase 2

"""Shared execution-provider selection — `docs/apis/v3-deepdive-02-inference-api.md` §8.6's
own "the shared session/EP-selection utility... generic-enough plumbing to live outside
either domain [OCR or Inference]... building an ordered `providers=[...]` list from a
hardware profile plus a config'd preference is identical logic whether the caller is
RapidOCR or an ONNX GenAI model." This is that utility — designed once, never built until
now (confirmed live: nothing in this repo ever called anything like this before tonight).

**Structural typing on purpose, not a `services.setup.contracts.HardwareProfile` import.**
`docs/PRINCIPLES.md` §1.3 and this repo's own established convention (`core/inference/
contracts.py`'s own `BlobRef`, re-declared rather than imported from
`core.persistence.contracts`, "this package's own Protocol only ever needs `.logical_id`")
apply identically here: `common/` sits beneath every service, including Setup itself, so a
real import of `services.setup.contracts` would risk exactly the kind of cross-layer
dependency this project's package layout exists to prevent. `GpuLike` names only the four
attributes this module actually reads; `services.setup.contracts.GpuInfo` already satisfies
it structurally with zero conversion needed at any real call site.
"""

from __future__ import annotations

import platform
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

__all__ = ["GpuLike", "select_execution_provider"]


@runtime_checkable
class GpuLike(Protocol):
    """The whole shape this module needs from a detected GPU — `services.setup.contracts.
    GpuInfo` already has exactly these four attributes, so passing `HardwareProfile.gpus`
    directly here needs no conversion at any real call site."""

    vendor: str
    compute_api: str
    discrete: bool
    vram_gb: float | None


def select_execution_provider(gpus: Iterable[GpuLike], *, os_name: str | None = None) -> str:
    """Picks this project's own device vocabulary string (`"cpu"`/`"cuda"`/`"directml"`/
    `"openvino"`) from a real, detected GPU list — never guessed, matching
    `services/setup/hardware/detect.py`'s own "never guess a number" discipline one level
    up. Falls back to `"cpu"` for no GPU, an unclassifiable vendor, or a compute API this
    project doesn't yet have a working EP path for (AMD/ROCm today — see below).

    Picks the best *discrete* GPU by VRAM when more than one exists (an integrated GPU is
    never preferred over a discrete one, matching `detect.py`'s own discrete-classification
    intent); among GPUs of equal discreteness, the one with more VRAM wins.

    `os_name` defaults to the real `platform.system()` — overridable so this stays a pure,
    synchronous, unit-testable function with no live-hardware dependency in its own tests,
    the same posture `detect.py`'s own `parse_windows_probe`/`parse_linux_probe` establish
    for hardware parsing one level below this.
    """
    resolved_os = os_name if os_name is not None else platform.system()

    best: GpuLike | None = None
    for gpu in gpus:
        if best is None:
            best = gpu
            continue
        if (gpu.discrete, gpu.vram_gb or 0) > (best.discrete, best.vram_gb or 0):
            best = gpu

    if best is None:
        return "cpu"

    if best.compute_api == "cuda":
        return "cuda"

    if best.compute_api == "sycl":
        # Intel's real EP split (deep-dive §8.1): DirectML is the broadly-compatible
        # Windows path; OpenVINO is Intel's own, actively-developed path elsewhere.
        return "directml" if resolved_os == "Windows" else "openvino"

    if best.compute_api == "rocm":
        # Real, deliberate, not an oversight: the classic ROCm execution provider was
        # removed from ONNX Runtime as of the 1.23 release, and MIGraphX (the current AMD
        # path) has no official Windows GPU path at all yet (deep-dive §8.1, corrected
        # from an earlier version of the OCR deep-dive that listed both as live options).
        # Attempting either EP here would be exactly the "assume acceleration from an EP's
        # mere presence" mistake §8.5 warns against — CPU is the honest current answer.
        return "cpu"

    return "cpu"

"""OpenCL/UMat device selection (deep-dive §6.1-6.2).

**Decision, reconfirmed by this module rather than re-argued**: OpenCV's Transparent API
(`cv2.UMat`) is the default GPU path — vendor-agnostic, ships in the standard `opencv-python`
wheel, and dispatches the *same* function calls (`cv2.threshold`, `cv2.cvtColor`,
`cv2.warpAffine`, ...) to an OpenCL-capable device transparently, falling back to CPU when none
is present. CUDA (`cv2.cuda_GpuMat`) is deliberately not built here — it needs a custom-compiled
OpenCV build, a real, meaningful extra-install cost this project's existing bias against
special/heavy builds already rules out as a default (§6.2).

`device_preference` is a plain `str` on `VariantRequest` (`"auto" | "cpu" | "opencl"`) —
resolved to a concrete boolean ("wrap this array in `cv2.UMat` before processing, yes or no")
by `resolve_device` below, which is the one function every variant-generation call site uses
rather than each re-checking `cv2.ocl.haveOpenCL()` independently.
"""

from __future__ import annotations

import cv2
import numpy as np

__all__ = ["resolve_device", "to_processing_array"]


def resolve_device(device_preference: str) -> str:
    """Returns `"opencl"` or `"cpu"` — the concrete device this call will actually run on,
    never the caller's raw preference string echoed back unresolved (a `"auto"` caller needs to
    know what it actually got, the same reason `EngineReading.device` exists on the OCR side).
    """
    if device_preference == "cpu":
        return "cpu"
    if device_preference == "opencl":
        if not cv2.ocl.haveOpenCL():
            # A caller explicitly asked for OpenCL on a machine with no capable device —
            # degrade to CPU rather than raise (docs/PRINCIPLES.md §4.4), the same posture
            # every other optional-hardware-acceleration path in this project takes.
            return "cpu"
        return "opencl"
    # "auto" (and any other value — never crash on an unrecognized preference string, degrade
    # to the always-available CPU path instead)
    return "opencl" if cv2.ocl.haveOpenCL() else "cpu"


def to_processing_array(image: np.ndarray, device: str) -> np.ndarray | cv2.UMat:
    """Wraps `image` in a `cv2.UMat` when `device == "opencl"`; returns it unchanged otherwise.

    Every OpenCV call in this package's variant generators works identically on a plain
    `numpy.ndarray` or a `cv2.UMat` — that is the whole point of the Transparent API (§6.1) —
    so this is the one place the wrap decision happens, not scattered through every generator.
    """
    if device == "opencl":
        return cv2.UMat(image)
    return image

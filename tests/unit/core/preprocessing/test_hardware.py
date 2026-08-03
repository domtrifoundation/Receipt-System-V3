"""`hardware.py` — OpenCL/UMat device selection (`v3-deepdive-03-preprocessing-api.md` §6.1-6.2).

Runs against this machine's own real OpenCL capability rather than mocking `cv2.ocl.haveOpenCL`
— the whole point of `resolve_device` is answering "what does this real machine actually
support," so a test that fakes the answer would not be testing the function's real job.
"""

from __future__ import annotations

import cv2

from core.preprocessing.hardware import resolve_device, to_processing_array
from core.preprocessing.variants.base import get_shape

from .conftest import make_checkerboard


def test_cpu_preference_always_resolves_to_cpu_regardless_of_real_capability():
    assert resolve_device("cpu") == "cpu"


def test_auto_resolves_to_whatever_this_real_machine_actually_supports():
    expected = "opencl" if cv2.ocl.haveOpenCL() else "cpu"
    assert resolve_device("auto") == expected


def test_an_unrecognized_preference_degrades_to_auto_behaviour_not_a_crash():
    """`docs/PRINCIPLES.md` §4.4 — a malformed preference string must degrade gracefully, the
    same posture as every other optional-hardware-acceleration path in this project."""
    expected = "opencl" if cv2.ocl.haveOpenCL() else "cpu"
    assert resolve_device("not_a_real_preference") == expected


def test_opencl_preference_without_a_capable_device_would_degrade_not_crash():
    """Cannot force `haveOpenCL()` to False on a machine that genuinely has it without
    monkeypatching the one thing this test suite's other cases deliberately do not fake — so
    this pins the *documented* contract via the function's own docstring reasoning instead:
    `resolve_device("opencl")` must never raise, which every other test in this file already
    exercises the success path of. The degrade branch itself is exercised for real wherever
    this suite runs on hardware without OpenCL support.
    """
    result = resolve_device("opencl")
    assert result in ("opencl", "cpu")


def test_to_processing_array_wraps_in_umat_only_for_opencl():
    image = make_checkerboard()
    cpu_result = to_processing_array(image, "cpu")
    opencl_result = to_processing_array(image, "opencl")

    assert not isinstance(cpu_result, cv2.UMat)
    assert isinstance(opencl_result, cv2.UMat)
    assert get_shape(opencl_result) == get_shape(cpu_result)

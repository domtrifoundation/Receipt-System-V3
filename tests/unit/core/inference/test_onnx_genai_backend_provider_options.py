"""`_provider_options()` is pure Python (no `onnxruntime_genai` import at module level,
`onnx_genai_backend.py`'s own docstring) -- real, direct coverage without needing the
native library installed, matching every other "logic-only" test in this package.
"""

from __future__ import annotations

from core.inference.backends.onnx_genai_backend import _provider_options, _session_thread_overlay


def test_cuda_gets_device_id():
    assert _provider_options("cuda", "/models/phi4-mini") == {"device_id": "0"}


def test_tensorrt_gets_device_id_and_engine_cache():
    options = _provider_options("NvTensorRtRtx", "/models/phi4-mini")
    assert options["device_id"] == "0"
    assert options["trt_engine_cache_enable"] == "1"
    assert options["trt_engine_cache_path"].endswith("trt_cache")


def test_openvino_defaults_to_cpu_device_type():
    """Real, live-confirmed finding, not a cautious guess: this project's own
    int4-quantized ONNX exports use dynamic sequence-length shapes OpenVINO's GPU/NPU
    compiler cannot handle -- `device_type=GPU` silently falls back to CPU internally
    rather than failing loudly, so CPU is the only device_type this function can
    honestly claim actually runs on the device it says it does."""
    assert _provider_options("OpenVINOExecutionProvider", "/models/phi4-mini") == {"device_type": "CPU"}


def test_unrecognized_provider_gets_no_options():
    assert _provider_options("qnn", "/models/phi4-mini") == {}
    assert _provider_options("dml", "/models/phi4-mini") == {}


def test_session_thread_overlay_uses_half_the_detected_cores():
    """Real fix for real, live-observed CPU contention between Inference and
    concurrently-running OCR (`core/inference/CLAUDE.md`) -- half, not all, of the
    detected core count."""
    overlay = _session_thread_overlay(cpu_count=24)
    session_options = overlay["model"]["decoder"]["session_options"]
    assert session_options["intra_op_num_threads"] == 12
    assert session_options["inter_op_num_threads"] == 1


def test_session_thread_overlay_never_goes_below_one_thread():
    overlay = _session_thread_overlay(cpu_count=1)
    assert overlay["model"]["decoder"]["session_options"]["intra_op_num_threads"] == 1


def test_session_thread_overlay_degrades_to_four_cores_worth_when_cpu_count_unknown(monkeypatch):
    """`os.cpu_count()` can return `None` on some platforms -- degrade to a real,
    reasoned default rather than crashing on `None // 2`."""
    import os

    monkeypatch.setattr(os, "cpu_count", lambda: None)
    overlay = _session_thread_overlay()
    assert overlay["model"]["decoder"]["session_options"]["intra_op_num_threads"] == 2

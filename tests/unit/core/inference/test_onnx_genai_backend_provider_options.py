"""`_provider_options()` is pure Python (no `onnxruntime_genai` import at module level,
`onnx_genai_backend.py`'s own docstring) -- real, direct coverage without needing the
native library installed, matching every other "logic-only" test in this package.
"""

from __future__ import annotations

from core.inference.backends.onnx_genai_backend import _provider_options


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

"""A fake `InferenceBackend`, module-level (not inside `conftest.py`) so it survives
being pickled by reference to a real `multiprocessing.Process` under Windows's `spawn`
start method — the same reason `core/preprocessing/generation.py`'s and `core/ocr/
generated`'s own test fakes live at module scope rather than as closures
(`test_generation.py`'s own module docstring explains the pickling constraint directly).

This lets `test_generation.py`/`test_model_registry.py` exercise the *real*
`multiprocessing.Process`/`Queue` mechanics, the real micro-batch drain loop, and real
crash-isolation behaviour — without needing real `onnxruntime_genai` or real model
weights, which this development session never downloaded (see `backends/
onnx_genai_backend.py`'s own module docstring for why).
"""

from __future__ import annotations

import time

from core.inference.backends.base import BackendGenerationOutput
from core.inference.contracts import FinishReason


class FakeBackend:
    def __init__(self) -> None:
        self.loaded = False

    def load(self, model_dir: str, device: str) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def generate(self, prompt: str, *, grammar_schema, max_tokens: int, temperature: float) -> BackendGenerationOutput:
        if "CRASH" in prompt:
            raise RuntimeError("simulated native crash")
        if "SLOW" in prompt:
            time.sleep(1.0)
        if "TOOLCALL" in prompt and grammar_schema is not None:
            import json

            return BackendGenerationOutput(
                text=json.dumps({"tool": "lookup_vendor", "arguments": {"name": "Dunkin"}}),
                finish_reason=FinishReason.STOP,
            )
        if "TRUNCATE" in prompt:
            return BackendGenerationOutput(
                text='{"vendor": "Dunkin"', finish_reason=FinishReason.LENGTH,
            )
        return BackendGenerationOutput(text=f"echo: {prompt[:40]}", finish_reason=FinishReason.STOP)


def make_fake_backend() -> FakeBackend:
    return FakeBackend()


class FailingLoadBackend:
    def load(self, model_dir: str, device: str) -> None:
        from core.inference.errors import ModelLoadFailed

        raise ModelLoadFailed("simulated missing model directory")

    def unload(self) -> None:
        pass

    def generate(self, prompt: str, *, grammar_schema, max_tokens: int, temperature: float):
        raise RuntimeError("never reached")


def make_failing_backend() -> FailingLoadBackend:
    return FailingLoadBackend()

"""`resolve_variant_path()` against a fake `huggingface_hub.list_repo_files` — never
live-tested before this suite existed (`presets.py`'s own module docstring says so
explicitly). A real live call against `microsoft/Phi-4-mini-instruct-onnx` is what caught
the bug this suite now pins down: the real repo layout nests each variant one directory
below the family name (`cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/model.onnx`), and
the original implementation returned only the first path segment.
"""

from __future__ import annotations

import pytest

from core.inference import presets as presets_module
from core.inference.presets import resolve_variant_path


class _FakeHfHub:
    def __init__(self, files: list[str]) -> None:
        self.files = files
        self.requested_repo: str | None = None

    def list_repo_files(self, repo: str) -> list[str]:
        self.requested_repo = repo
        return self.files


@pytest.fixture(autouse=True)
def _stub_huggingface_hub(monkeypatch):
    """`resolve_variant_path` imports `huggingface_hub.list_repo_files` lazily *inside*
    the function (`# noqa: PLC0415`), so patching the real top-level module is what
    actually reaches it -- patching `core.inference.presets.list_repo_files` would silently
    no-op since no such name is ever bound in this module's namespace."""
    fake = _FakeHfHub([])

    import types

    fake_module = types.ModuleType("huggingface_hub")
    fake_module.list_repo_files = fake.list_repo_files
    monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", fake_module)
    yield fake


def test_resolves_the_real_nested_variant_directory_not_the_top_level_folder(_stub_huggingface_hub):
    """The exact real-world shape that caught this bug live: variant files live one
    directory below the family folder, not directly inside it."""
    _stub_huggingface_hub.files = [
        "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/genai_config.json",
        "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/model.onnx",
        "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/model.onnx.data",
        "gpu/gpu-int4-rtn-block-32/genai_config.json",
        "gpu/gpu-int4-rtn-block-32/model.onnx",
    ]

    result = resolve_variant_path("phi4-mini", "cpu")

    assert result == "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4"


def test_resolves_the_gpu_variant_for_a_gpu_device_family(_stub_huggingface_hub):
    _stub_huggingface_hub.files = [
        "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/genai_config.json",
        "gpu/gpu-int4-rtn-block-32/genai_config.json",
        "gpu/gpu-int4-rtn-block-32/model.onnx",
    ]

    result = resolve_variant_path("phi4-mini", "cuda")

    assert result == "gpu/gpu-int4-rtn-block-32"


def test_no_matching_variant_raises_value_error(_stub_huggingface_hub):
    _stub_huggingface_hub.files = [
        "cpu_and_mobile/cpu-int8-rtn-block-32/genai_config.json",
    ]

    with pytest.raises(ValueError, match="no variant folder"):
        resolve_variant_path("phi4-mini", "cpu")


def test_unknown_preset_raises_key_error(_stub_huggingface_hub):
    with pytest.raises(KeyError):
        resolve_variant_path("no-such-preset", "cpu")


def test_unknown_device_family_raises_value_error(_stub_huggingface_hub):
    _stub_huggingface_hub.files = ["cpu_and_mobile/cpu-int4-rtn-block-32/genai_config.json"]

    with pytest.raises(ValueError, match="no variant hint"):
        resolve_variant_path("phi4-mini", "rocm")

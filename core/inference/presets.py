"""Named model presets (deep-dive §4.4) — Hugging Face repo + Model Builder config, with
live-resolved quantization variants rather than a hardcoded subfolder path.

**Not live-resolved against the real Hugging Face Hub this session.** `resolve_variant_
path()` below calls `huggingface_hub`'s own repo-listing API, lazily imported and never
invoked during this session (no model download happened — downloading is one of this
project's own "ask the user first" actions, and there was nothing to download for since no
preset was actually loaded). The self-healing *design* mirrors OCR API's own model-currency
technique exactly; the *live network call* itself is unverified, the same honesty posture
`backends/onnx_genai_backend.py`'s own module docstring takes.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

__all__ = ["MODEL_PRESETS", "PresetSpec", "resolve_variant_path"]

#: `MM` per-preset entries are `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1) — a read-only
#: table shared across threads under free-threading. `variant_hints` maps a device family
#: ("cpu"/"cuda"/"directml") to a `(precision_tag, quant_tag)` pair used to narrow the
#: live repo listing (`resolve_variant_path`), not a literal subfolder path — the exact
#: folder layout is confirmed live at download time since it can shift between releases.
MODEL_PRESETS: FrozenDict = FrozenDict({
    "phi4-mini": FrozenDict({
        "repo": "microsoft/Phi-4-mini-instruct-onnx",
        "variant_hints": FrozenDict({
            "cpu": ("cpu", "int4"), "cuda": ("gpu", "int4"), "directml": ("gpu", "int4"),
        }),
        "context_window": 128_000, "supports_tools": True, "supports_vision": False,
        #: A reasoned placeholder, not a bench-measured figure (same posture as OCR's own
        #: RapidOCR/PaddleOCR VRAM estimates) — Phi-4-mini int4 is roughly a 3.8B-parameter
        #: model; int4 weight-only quantization puts raw weights around 2GB, plus KV-cache
        #: and activation overhead. Refine from real measurement once the bench suite and
        #: a real download exist — this number gates a Health API reservation call
        #: (deep-dive §8.6), not a hard resource limit enforced elsewhere.
        "estimated_vram_mb": 3_000,
    }),
    "phi4-vision": FrozenDict({
        "repo": "microsoft/Phi-4-multimodal-instruct-onnx",
        "variant_hints": FrozenDict({
            "cpu": ("cpu", "int4"), "cuda": ("gpu", "int4"), "directml": ("gpu", "int4"),
        }),
        "context_window": 128_000, "supports_tools": False, "supports_vision": True,
        #: Larger than the text-only preset above — a multimodal vision encoder adds real
        #: weight beyond the base language model. Same "reasoned placeholder, not
        #: measured" caveat applies.
        "estimated_vram_mb": 5_000,
    }),
})


class PresetSpec:
    """A typed, read-only view over one `MODEL_PRESETS` entry — callers index
    `MODEL_PRESETS` directly for the raw `FrozenDict`, or go through this for attribute
    access without repeating `.get("key")` calls at every use site."""

    def __init__(self, name: str) -> None:
        if name not in MODEL_PRESETS:
            raise KeyError(name)
        self.name = name
        self._raw = MODEL_PRESETS[name]

    @property
    def repo(self) -> str:
        return self._raw["repo"]

    @property
    def context_window(self) -> int:
        return self._raw["context_window"]

    @property
    def supports_tools(self) -> bool:
        return self._raw["supports_tools"]

    @property
    def supports_vision(self) -> bool:
        return self._raw["supports_vision"]

    @property
    def estimated_vram_mb(self) -> int:
        return self._raw["estimated_vram_mb"]

    def variant_hint(self, device_family: str) -> tuple[str, str] | None:
        return self._raw["variant_hints"].get(device_family)


def resolve_variant_path(preset_name: str, device_family: str) -> str:
    """Resolves the real subfolder inside a preset's repo for the given device family,
    from the **live repo listing**, never a hardcoded path (deep-dive §4.4's own
    self-healing technique, matching OCR API's model-currency approach).

    Raises `KeyError`/`ValueError` for a caller error (unknown preset, unknown device
    family, or an entirely unreachable repo listing) — this is a startup-time resolution
    step, not a per-request one, so a failure here belongs to `model_registry.py`'s own
    `ModelLoadFailed` path rather than a per-generation error.
    """
    spec = PresetSpec(preset_name)
    hint = spec.variant_hint(device_family)
    if hint is None:
        raise ValueError(f"preset {preset_name!r} has no variant hint for device family {device_family!r}")
    precision_tag, quant_tag = hint

    from huggingface_hub import list_repo_files  # noqa: PLC0415

    files = list_repo_files(spec.repo)
    candidates = sorted(
        {f.split("/")[0] for f in files if "/" in f and precision_tag in f and quant_tag in f}
    )
    if not candidates:
        raise ValueError(
            f"no variant folder in {spec.repo!r} matched hint ({precision_tag}, {quant_tag})"
        )
    return candidates[0]

"""Named model presets (deep-dive §4.4) — Hugging Face repo + Model Builder config, with
live-resolved quantization variants rather than a hardcoded subfolder path.

**Live-resolved against the real Hugging Face Hub**, given explicit permission for a real
model-download test — `resolve_variant_path()` below is what actually caught its own two
real bugs (see its docstring), confirmed live against `microsoft/Phi-4-mini-instruct-onnx`
and `microsoft/Phi-4-multimodal-instruct-onnx`'s real file listings, not left unverified.
`model_provisioning.py` is the real provisioning path this module's own resolution feeds —
see that module's own docstring for the "who downloads it" side of this design.
"""

from __future__ import annotations

from collections.abc import Callable

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
        #: `None` — a non-reasoning instruct preset (deep-dive §12's own resolved default:
        #: "non-reasoning instruct presets only, by default"). A future reasoning-tuned
        #: preset sets this to its own real thinking-segment closing tag (e.g.
        #: `"</think>"`) to opt into the §4.5 two-phase budget; `generation.py` treats
        #: `None` as "no reasoning phase at all," the correct behavior for every preset
        #: actually shipped today.
        "reasoning_marker": None,
    }),
    "phi4-vision": FrozenDict({
        "repo": "microsoft/Phi-4-multimodal-instruct-onnx",
        #: No `"cpu"` entry, live-confirmed against the real repo listing rather than
        #: assumed symmetric with `phi4-mini` above: this repo ships exactly one packaged,
        #: `og.Model`-loadable variant (`gpu/gpu-int4-rtn-block-32`) plus a bare `onnx/`
        #: folder of Model Builder *source* (`builder.py`, `modeling_phi4mm.py`, ...), not
        #: a second ready-to-load variant. A `"cpu": ("cpu", "int4")` entry here matched
        #: nothing in `resolve_variant_path()` and would only ever raise `ValueError` --
        #: correct in outcome (fails loudly, never silently wrong) but a false claim in
        #: the data itself. `variant_hint("cpu")` now honestly returns `None`.
        "variant_hints": FrozenDict({
            "cuda": ("gpu", "int4"), "directml": ("gpu", "int4"),
        }),
        "context_window": 128_000, "supports_tools": False, "supports_vision": True,
        #: Larger than the text-only preset above — a multimodal vision encoder adds real
        #: weight beyond the base language model. Same "reasoned placeholder, not
        #: measured" caveat applies.
        "estimated_vram_mb": 5_000,
        "reasoning_marker": None,
    }),
    "qwen2.5-3b": FrozenDict({
        #: A real, live-found second repo shape: `keisuke-miyako/Qwen2.5-3B-Instruct-
        #: onnx-int4` ships as a single flat build (every file at the repo root, real
        #: `genai_config.json` present, confirmed live via `list_repo_files` before
        #: adding this entry) rather than Microsoft's own tagged-subfolder-per-variant
        #: convention `resolve_variant_path()` was originally built against. This preset
        #: exists specifically to test a real, direct hypothesis about V3's own
        #: performance against a same-ish-size model (~3B) on the identical hardware and
        #: backend as `phi4-mini` -- not a hardcoded assumption that a differently-shaped
        #: repo can't be a real preset. `variant_hints` below still supplies real tags
        #: (matching the other presets' own convention) even though a flat repo's own
        #: fallback in `resolve_variant_path()` ignores them once no tagged subfolder
        #: exists -- keeping every preset's `variant_hints` shape uniform is worth more
        #: than saving three tuples here.
        "repo": "keisuke-miyako/Qwen2.5-3B-Instruct-onnx-int4",
        "variant_hints": FrozenDict({
            "cpu": ("cpu", "int4"), "cuda": ("gpu", "int4"), "directml": ("gpu", "int4"),
        }),
        "context_window": 32_768, "supports_tools": True, "supports_vision": False,
        #: Reasoned placeholder, not bench-measured -- same caveat as every other
        #: preset's own `estimated_vram_mb` here. Qwen2.5-3B int4 weight-only
        #: quantization is roughly 1.5-2GB of raw weights; sized a little above that for
        #: KV-cache/activation overhead, the same reasoning `phi4-mini`'s own estimate
        #: documents.
        "estimated_vram_mb": 2_500,
        "reasoning_marker": None,
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

    @property
    def reasoning_marker(self) -> str | None:
        return self._raw["reasoning_marker"]

    def variant_hint(self, device_family: str) -> tuple[str, str] | None:
        return self._raw["variant_hints"].get(device_family)


def resolve_variant_path(
    preset_name: str, device_family: str, *, list_repo_files_fn: Callable[[str], list[str]] | None = None
) -> str:
    """Resolves the real subfolder inside a preset's repo for the given device family,
    from the **live repo listing**, never a hardcoded path (deep-dive §4.4's own
    self-healing technique, matching OCR API's model-currency approach).

    Raises `KeyError`/`ValueError` for a caller error (unknown preset, unknown device
    family, or an entirely unreachable repo listing) — this is a startup-time resolution
    step, not a per-request one, so a failure here belongs to `model_registry.py`'s own
    `ModelLoadFailed` path rather than a per-generation error.

    `list_repo_files_fn`, if given, replaces the real Hub call — real reason, not just
    testability: `model_provisioning.list_remote_variant_files()` already fetches every
    file's name *and size* from the Hub in one call of its own, and re-deriving the
    variant folder from that same already-fetched list (rather than this function making
    its own second, redundant Hub round trip) is both cheaper and the only way for that
    caller's own tests to exercise this resolution without a real network call either.
    """
    spec = PresetSpec(preset_name)
    hint = spec.variant_hint(device_family)
    if hint is None:
        raise ValueError(f"preset {preset_name!r} has no variant hint for device family {device_family!r}")
    precision_tag, quant_tag = hint

    if list_repo_files_fn is not None:
        files = list_repo_files_fn(spec.repo)
    else:
        from huggingface_hub import list_repo_files  # noqa: PLC0415

        files = list_repo_files(spec.repo)
    # Real, live-found bug, caught only by actually calling this against the real Hub
    # (permission granted, not hypothetical): `f.split("/")[0]` returns the repo's
    # top-level folder ("cpu_and_mobile"), never the actual model directory one level
    # deeper that holds `genai_config.json`/`model.onnx`
    # ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4") -- confirmed live against
    # `microsoft/Phi-4-mini-instruct-onnx`'s real file listing. The full directory
    # (everything but the filename) is the actual variant path; every file inside one
    # variant folder shares the same dirname, so this still resolves to exactly one
    # candidate per real variant, not one per file.
    candidates = sorted(
        {
            "/".join(f.split("/")[:-1])
            for f in files
            if "/" in f and precision_tag in f and quant_tag in f
        }
    )
    if candidates:
        return candidates[0]

    # Real, live-found second repo shape, not a hypothetical: a growing number of
    # community genai-format exports (e.g. Qwen2.5 conversions) ship as exactly one
    # build with every file directly at the repo root -- no `cpu_and_mobile/<tag>/`
    # nesting to disambiguate, because there is nothing to disambiguate among. Requiring
    # a tag match here would raise `no variant folder matched` against a real, loadable
    # repo purely because Microsoft's own multi-variant convention doesn't apply to it.
    # A flat repo (no file anywhere contains a `/`) has exactly one variant by
    # construction, so it is unconditionally that variant regardless of which
    # precision/quant tag was requested -- the empty string, meaning "the repo root
    # itself" to `model_provisioning.py`'s own prefix-stripping callers.
    if files and not any("/" in f for f in files):
        return ""

    raise ValueError(
        f"no variant folder in {spec.repo!r} matched hint ({precision_tag}, {quant_tag})"
    )

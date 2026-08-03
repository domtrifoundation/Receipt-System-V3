"""The one and only backend: `onnxruntime-genai` (deep-dive §4.1-§4.2, §5, §8).

**Not live-tested against real model weights this session.** Downloading a real ONNX
GenAI model directory (multi-GB, per §4.3) is an action this session does not take without
explicit user permission (downloading files is one of this project's own "ask first"
actions) — so this module is built directly from `onnxruntime-genai`'s own published
Python API and release notes (`og.Model`/`og.Config`/`og.Tokenizer`/`og.GeneratorParams`/
`og.Generator`, and the library's own LLGuidance-based `set_guidance(type, data)`
constrained-decoding call), not verified end-to-end the way Preprocessing's and OCR's own
engines were against real hardware and real receipts. This is the same honesty posture
this package already applies to `core/ocr/engines/apple_vision_engine.py` — say plainly
what was and wasn't run for real, rather than imply parity with the modules that were.

**Execution-provider selection (deep-dive §8.1) — implemented, confidence varies by
provider, stated explicitly rather than left implicit.** `onnxruntime-genai`'s own
`Config` object (`og.Config(model_dir)` -> `config.clear_providers()` ->
`config.append_provider(name)` -> `og.Model(config)`) is the real, documented mechanism
for selecting a non-default execution provider, confirmed against the library's own
published example scripts (its `model-qa.py`/benchmarking tooling uses exactly this
sequence). `_PROVIDER_NAMES` below maps this project's own `device` vocabulary to the
provider-name strings that mechanism expects:
- `"cuda"` -> `"cuda"`, `"directml"` -> `"dml"`: **high confidence** — these two are the
  most commonly documented/exercised EPs in onnxruntime-genai's own examples.
- `"rocm"`/`"migraphx"` -> `"rocm"`, `"qnn"` -> `"qnn"`: **medium confidence** — named in
  release notes, less commonly exercised in example code than the two above.
- `"openvino"`, `"tensorrt"`: **low confidence** — OpenVINO/TensorRT-RTX support in
  `onnxruntime-genai` specifically (as opposed to plain `onnxruntime`) is newer and this
  session could not confirm the exact provider-name string the library expects for
  either. Attempted anyway with the most likely string per public documentation, but
  flagged here so a real install failure on one of these two specifically is not a
  surprise — it is the expected shape of what "unverified" means for exactly these two.

Session-level settings from deep-dive §8.2 (IOBinding, CUDA graph capture, graph
optimization level, memory arena tuning, `intra_op`/`inter_op` thread counts) are
**not implemented** — these are controlled through `genai_config.json`'s own schema
inside the downloaded model directory in current `onnxruntime-genai` versions, not through
a separate Python-level session-options object the way raw `onnxruntime` exposes them, and
verifying the exact JSON schema keys needs a real model directory to test against. Provider
*options* (e.g. CUDA's own `device_id`) are attempted via `config.set_provider_option(...)`
below, same confidence caveat as the provider-name mapping itself.

`onnxruntime_genai` is imported lazily inside `load()`/`generate()`, never at module level
— an install without it (the common case for a fresh checkout before Setup API's wizard
resolves and installs the right one of the three `onnxruntime-genai*` packages, §4.2)
degrades this backend to unavailable rather than failing this module's own import
(`docs/PRINCIPLES.md` §3.3 point 5).
"""

from __future__ import annotations

import json

from ..contracts import ContentBlockType, FinishReason, Message, MessageRole
from ..errors import GenerationCrashed, ModelLoadFailed
from .base import BackendGenerationOutput

__all__ = ["OnnxGenAiBackend", "build_prompt"]

#: This project's own `device` vocabulary -> the provider-name string
#: `og.Config.append_provider()` expects. `"cpu"` is deliberately absent — it needs no
#: provider appended at all (the CPU EP is `onnxruntime-genai`'s own built-in default).
_PROVIDER_NAMES: dict[str, str] = {
    "cuda": "cuda",
    "directml": "dml",
    "rocm": "rocm",
    "migraphx": "rocm",  # MIGraphX runs on top of the ROCm platform layer (OCR deep-dive §5.1's own correction, cross-referenced in this API's own §8.1)
    "qnn": "qnn",
    "openvino": "OpenVINOExecutionProvider",  # low confidence — see module docstring
    "tensorrt": "NvTensorRtRtx",  # low confidence — see module docstring
}


def build_prompt(messages: tuple[Message, ...]) -> str:
    """A basic, deliberately simple role-tagged prompt template.

    **Not a real per-model chat template.** Every serious instruct-tuned model family
    ships its own exact chat-template format (Phi-4's, Qwen's, and so on typically differ
    in their exact special-token spelling) — reproducing each one correctly needs testing
    against that family's own real tokenizer/template, which needs the real model
    downloaded. Until a preset is validated against its own real chat template, this
    generic `<|role|>\\ncontent` shape is a known, stated placeholder, not a finished
    design — flagged here rather than presented as more complete than it is.
    """
    lines: list[str] = []
    for message in messages:
        text_parts = [block.text for block in message.content if block.type == ContentBlockType.TEXT and block.text]
        lines.append(f"<|{message.role.value}|>\n{' '.join(text_parts)}")
    lines.append(f"<|{MessageRole.ASSISTANT.value}|>\n")
    return "\n".join(lines)


class OnnxGenAiBackend:
    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None
        self._device = "cpu"

    def load(self, model_dir: str, device: str) -> None:
        try:
            import onnxruntime_genai as og  # noqa: PLC0415
        except ImportError as exc:
            raise ModelLoadFailed(f"onnxruntime_genai is not installed: {exc}") from exc

        provider_name = _PROVIDER_NAMES.get(device)
        try:
            if provider_name is not None:
                # Real EP-selection mechanism (deep-dive §8.1) — see module docstring for
                # the per-provider confidence caveats.
                config = og.Config(model_dir)
                config.clear_providers()
                config.append_provider(provider_name)
                self._model = og.Model(config)
            else:
                # "cpu" (or an unrecognized device string — degrade to CPU rather than
                # fail the load over a config typo, `docs/PRINCIPLES.md` §4.4) needs no
                # provider appended at all; CPU is onnxruntime-genai's own built-in default.
                self._model = og.Model(model_dir)
            self._tokenizer = og.Tokenizer(self._model)
        except Exception as exc:  # noqa: BLE001 - any construction failure is a load failure
            raise ModelLoadFailed(f"{type(exc).__name__}: {exc}") from exc
        self._device = device if provider_name is not None else "cpu"

    def unload(self) -> None:
        self._tokenizer = None
        self._model = None

    def generate(
        self,
        prompt: str,
        *,
        grammar_schema: dict | None,
        max_tokens: int,
        temperature: float,
    ) -> BackendGenerationOutput:
        if self._model is None or self._tokenizer is None:
            raise ModelLoadFailed("generate() called before a successful load()")

        try:
            import onnxruntime_genai as og  # noqa: PLC0415

            input_ids = self._tokenizer.encode(prompt)
            params = og.GeneratorParams(self._model)
            params.set_search_options(
                max_length=len(input_ids) + max_tokens,
                temperature=max(temperature, 1e-4),
                do_sample=temperature > 0.0,
            )
            if grammar_schema is not None:
                # LLGuidance-based constrained decoding (deep-dive §5) — every token
                # masked to schema-valid continuations. Method name/signature per
                # onnxruntime-genai's own published examples; unverified against real
                # weights this session (see module docstring).
                params.set_guidance("json_schema", json.dumps(grammar_schema))

            generator = og.Generator(self._model, params)
            generator.append_tokens(input_ids)
            tokenizer_stream = self._tokenizer.create_stream()

            text_parts: list[str] = []
            tokens_generated = 0
            while not generator.is_done():
                generator.generate_next_token()
                new_token = generator.get_next_tokens()[0]
                text_parts.append(tokenizer_stream.decode(new_token))
                tokens_generated += 1
        except Exception as exc:  # noqa: BLE001 - a native generation failure is a crash
            raise GenerationCrashed(f"{type(exc).__name__}: {exc}") from exc

        text = "".join(text_parts)
        finish_reason = FinishReason.LENGTH if tokens_generated >= max_tokens else FinishReason.STOP

        schema_valid = True
        if grammar_schema is not None:
            schema_valid = _validate_against_schema(text, grammar_schema)

        return BackendGenerationOutput(
            text=text, finish_reason=finish_reason, schema_valid=schema_valid,
        )


def _validate_against_schema(text: str, schema: dict) -> bool:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    try:
        import jsonschema  # noqa: PLC0415

        jsonschema.validate(parsed, schema)
        return True
    except ImportError:
        # No jsonschema installed — a successful JSON parse is the best signal available
        # without it; constrained decoding's own guarantee is what actually keeps this
        # honest, this is a secondary check.
        return True
    except Exception:  # noqa: BLE001 - any validation failure means invalid
        return False

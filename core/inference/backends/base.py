"""`InferenceBackend` — the Protocol every generation backend implements (deep-dive §4.1).

**V3 ships exactly one backend, `onnx_genai_backend.py`** — the deep-dive's own resolved
decision to drop V2's second (`llama.cpp`) backend now that `onnxruntime-genai` covers
every Python version this project targets. This Protocol still exists as a real seam
(`docs/PRINCIPLES.md` §1.3) rather than a single hardcoded class, because "exactly one
backend today" is a current fact about the dependency landscape, not a permanent
architectural constraint — the same posture OCR API's engine `Protocol` takes even though
some of its own engines are platform-structural rather than swappable.

This Protocol is only ever implemented and called **inside a `PresetWorker`'s own child
process** (`generation.py`) — never inside Inference API's own service process, which never
imports `onnxruntime_genai`'s native bindings at all (deep-dive §6.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..contracts import FinishReason

__all__ = ["BackendGenerationOutput", "InferenceBackend"]


@dataclass(frozen=True)
class BackendGenerationOutput:
    """A backend's own raw output — `generation.py`'s worker loop adds `device` and
    `duration_ms` on top of this to build the real `GenerationResult` (those two fields
    are the worker's own bookkeeping, not the backend's concern)."""

    text: str
    finish_reason: FinishReason
    schema_valid: bool = True
    tool_call_json: str | None = None  # raw JSON text of a chosen tool call, if any


class InferenceBackend(Protocol):
    def load(self, model_dir: str, device: str) -> None:
        """Constructs and holds the loaded model. Raises `errors.ModelLoadFailed` on
        failure — called once, at worker startup, never per-request."""
        ...

    def unload(self) -> None:
        """Releases the loaded model's resources. Best-effort; called on worker shutdown."""
        ...

    def generate(
        self,
        prompt: str,
        *,
        grammar_schema: dict | None,
        max_tokens: int,
        temperature: float,
        images: tuple[bytes, ...] = (),
        reasoning_marker: str | None = None,
        reasoning_token_budget: int = 0,
    ) -> BackendGenerationOutput:
        """Runs one generation call against the already-loaded model. `grammar_schema` is
        a plain JSON Schema dict (already resolved by `structured_output.py`/
        `tool_calling.py`'s pure-Python logic in the parent process and carried across the
        queue as plain data) — compiling it into an actual constrained-decoding grammar
        object is this backend's own job, since a compiled grammar is native/unpicklable
        the same way a loaded model is. Raises `errors.GenerationCrashed` on failure.

        `images` is already-resolved raw image bytes (deep-dive §7) — `vision.py`'s own
        job is resolving a request's `image_ref`s to bytes before crossing to a worker;
        this backend's own job is doing whatever the vision-capable preset's own weights
        need with those bytes. Empty for a text-only request or a non-vision preset.

        `reasoning_marker`/`reasoning_token_budget` are deep-dive §4.5's own two-phase
        budget: a reasoning-tuned preset gets its own separate token budget for the
        thinking segment, switching to the schema-constrained grammar once the marker
        (e.g. a closing `</think>`-style tag) is seen or that budget is exhausted,
        whichever comes first. `reasoning_marker=None` (every preset actually shipped
        today, deep-dive §12's own "non-reasoning instruct presets only, by default"
        resolution) means no two-phase behavior at all — plain single-budget generation."""
        ...

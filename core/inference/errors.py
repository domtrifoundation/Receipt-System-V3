"""Inference API's error taxonomy.

`InferenceError` (`contracts.py`) is the wire-facing shape — never raised across this
API's own gRPC boundary (`docs/PRINCIPLES.md` §4.1). The exception classes below exist for
the *internal* call path only: `backends/onnx_genai_backend.py` and `generation.py`'s
worker loop raise these, and `model_registry.py`/`generation.py`'s own `PresetWorker` is
the one place they get caught and converted into a `GenerationResult` carrying an
`InferenceError` (mirroring `core/ocr/engine_registry.py`'s identical conversion point).
"""

from __future__ import annotations

__all__ = [
    "GenerationCrashed",
    "GenerationTimeout",
    "InferenceInternalError",
    "ModelLoadFailed",
    "PresetNotConfigured",
    "SchemaViolation",
    "WorkerUnavailable",
]


class InferenceInternalError(Exception):
    """Base for everything this package raises internally, never across its own boundary."""


class PresetNotConfigured(InferenceInternalError):
    """The requested preset name isn't in `presets.py`'s own table, or isn't in
    `engines_enabled`/`presets_enabled` — a caller error, discovered before any worker is
    even spawned."""


class ModelLoadFailed(InferenceInternalError):
    """A `PresetWorker`'s child process failed to construct `og.Model(...)` — a missing
    model directory, a corrupt/incomplete download, an unsupported device for this
    preset's own variant. Discovered once at worker startup, not mid-generation."""


class GenerationTimeout(InferenceInternalError):
    """The worker did not return within `GenerationRequest.timeout_ms`."""


class GenerationCrashed(InferenceInternalError):
    """The worker process was alive and generating, but the generation call itself raised
    — a malformed prompt, an out-of-memory kill surfaced as an exception, a genuinely
    unexpected native failure. Contained to that one worker process (deep-dive §6.1) —
    never propagates to Inference API's own service process or to any other preset's
    worker."""


class WorkerUnavailable(InferenceInternalError):
    """The preset's worker process is not alive (never started, or died and hasn't been
    reloaded yet) — distinct from `GenerationCrashed`, which is a failure *during* a call
    to a worker that was otherwise healthy."""


class SchemaViolation(InferenceInternalError):
    """Constrained-decoding output failed to validate against its own schema after a
    retry — should be rare by construction (deep-dive §5.1), essentially only reachable
    alongside a `LENGTH` finish reason where even the retried budget still truncated."""

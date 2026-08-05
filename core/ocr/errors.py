"""OCR API's error taxonomy.

`OcrError` (`contracts.py`) is the wire-facing shape — never raised across this API's own
gRPC boundary (`docs/PRINCIPLES.md` §4.1). The exception classes below exist for the
*internal* call path only: each engine adapter raises one of these, and `engine_registry.py`
is the one place they get caught and converted into an `EngineReading` carrying an
`OcrError` (mirroring `core/preprocessing/generation.py`'s own single conversion point for
its own worker exceptions).

`OcrEnginePlatformUnsupported` is its own subtype rather than a flavor of "unavailable"
because it needs to render differently in the Interface API's settings menu — "not
available on this OS" for Windows OCR on Linux, versus "not installed, run pip install" for
a missing optional dependency (deep-dive §4.5).
"""

from __future__ import annotations

__all__ = [
    "OcrAuthError",
    "OcrBudgetExceeded",
    "OcrEngineCrashed",
    "OcrEnginePlatformUnsupported",
    "OcrEngineTimeout",
    "OcrEngineUnavailable",
    "OcrInternalError",
    "OcrNetworkError",
    "OcrRateLimited",
]


class OcrInternalError(Exception):
    """Base for everything an engine adapter raises internally, never across this API's
    own boundary."""


class OcrEngineUnavailable(OcrInternalError):
    """A missing optional dependency, an unconfigured API key, or a startup sanity check
    (e.g. `pytesseract.get_tesseract_version()`) that failed — the engine cannot run at
    all, discovered once at registry-init or availability-probe time, not mid-call."""


class OcrEnginePlatformUnsupported(OcrInternalError):
    """The engine is structurally absent on this OS (Windows OCR on Linux, Apple Vision on
    anything but macOS) — a different category from a missing pip package."""


class OcrEngineCrashed(OcrInternalError):
    """The engine was available and ran, but raised during the actual read — a corrupt
    image, an inference-time exception, a segfault-adjacent native failure surfaced as a
    Python exception. Per-engine failures on individual receipts are expected/normal, not
    alarm-worthy (deep-dive §4.3)."""


class OcrEngineTimeout(OcrInternalError):
    """The engine did not return within `OcrRequest.timeout_ms`."""


class OcrBudgetExceeded(OcrInternalError):
    """A cloud engine call was refused before the network call happened because this run
    already spent its `max_calls_per_run` budget for that engine (deep-dive §4.7)."""


class OcrNetworkError(OcrInternalError):
    """A cloud engine's HTTP call failed at the transport level — DNS, connection refused,
    a timeout below `OcrEngineTimeout`'s own per-request budget. Deliberately distinct
    from `OcrAuthError`/`OcrRateLimited` (deep-dive §4.7): a transient network blip should
    surface differently in the Interface API than a bad API key."""


class OcrAuthError(OcrInternalError):
    """A cloud engine rejected the request's credentials (missing/invalid API key, expired
    token) — a 401/403-shaped response, distinct from a network failure or a rate limit."""


class OcrRateLimited(OcrInternalError):
    """A cloud engine's own rate limit rejected the call — a 429-shaped response, distinct
    from this API's own pre-call budget enforcement (`OcrBudgetExceeded`)."""

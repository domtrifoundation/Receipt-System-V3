"""Shared plumbing for the paid, network-bound cloud tier (deep-dive §4.7): Google Cloud
Vision, Azure Document Intelligence, AWS Textract. All three are the same *kind* of engine
and share this one budget/timeout/error-taxonomy base rather than three one-off
implementations.

**Never auto-enabled.** `engine_registry.py` enforces the actual per-run call budget
(deep-dive §4.7's own stated ownership) — `CloudEngineConfig.max_calls_per_run` is the
config value it checks against, not something this module enforces itself, since the
budget is a cross-call, per-run count that belongs with the registry's own request
dispatch, not duplicated inside each cloud adapter.

`classify_http_status` is the one place a raw HTTP status code becomes one of this API's
three cloud-specific exception types — auth failures, rate limits, and everything else
(network/5xx) render differently in the Interface API (deep-dive §4.7's own stated reason),
so collapsing them into one generic "cloud call failed" exception would lose exactly the
distinction this exists to preserve.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...errors import OcrAuthError, OcrNetworkError, OcrRateLimited

__all__ = ["CloudEngineConfig", "classify_http_status"]


@dataclass(frozen=True)
class CloudEngineConfig:
    api_key: str = ""  # empty = disabled regardless of engines_enabled (deep-dive §6)
    endpoint: str = ""  # only Azure needs this; harmless unused field for the other two
    max_calls_per_run: int = 50
    timeout_seconds: float = 15.0
    extra: dict = field(default_factory=dict)  # AWS's access_key_id/secret/region live here


def classify_http_status(status_code: int, detail: str) -> None:
    """Raises the matching exception for a non-2xx HTTP response; returns normally for a
    2xx one. A plain function rather than a method, since all three cloud engines call it
    identically on their own `httpx`/`boto3` response."""
    if status_code in (401, 403):
        raise OcrAuthError(detail)
    if status_code == 429:
        raise OcrRateLimited(detail)
    if status_code >= 500 or status_code == 0:
        raise OcrNetworkError(detail)
    if status_code >= 400:
        raise OcrNetworkError(detail)

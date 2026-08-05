"""Proving Grounds data contracts (`v3-deepdive-36-proving-grounds.md` §2, §4).

Types only, no logic (`docs/PRINCIPLES.md` §1.1) — the only module other packages import
from. `TestCandidate` covers both use cases §1 names: a dependency-version bump
(Telemetrees' Dependencies Warden surfaces "this exists now") and a code-release channel
candidate (Update API's own `ReleaseDirectory`, tested before promotion) — one shape for
both, since both reduce to "download this, run the affected bench workload against it,
report pass/fail."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

__all__ = [
    "CandidateKind",
    "DownloadResult",
    "ProvingGroundsMetrics",
    "TestCandidate",
    "TestHistoryEntry",
    "TestResult",
    "utcnow",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateKind(str, Enum):
    """§1's own two use cases — kept distinct because they name a different "affected
    thing" (`affected_api` is a dependency name for one, a release ref for the other) and a
    caller building a `TestCandidate` needs to say which it means."""

    DEPENDENCY_BUMP = "dependency_bump"
    CODE_RELEASE = "code_release"


@dataclass(frozen=True)
class TestCandidate:
    """One thing to test before it is trusted anywhere (§4's own `test_candidate()`
    signature).

    `affected_api` names which Core API's own bench suite this candidate exercises (`"ocr"`
    for an OCR engine bump, `"inference"` for an ONNX Runtime bump) — §1's own boundary:
    "reuses each affected API's own bench workload... never a separate testing methodology
    invented here." `download_url`/`hf_token` are `download.py`'s own inputs; both empty is
    legitimate for a `CODE_RELEASE` candidate, whose "download" is Update API's own
    `CloneRelease`, not this module's.
    """

    kind: CandidateKind
    name: str
    version: str
    affected_api: str
    download_url: str = ""
    hf_token: str = ""
    requested_by: str = ""
    requested_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class TestResult:
    """§4's own `test_candidate()` return value. Errors are data
    (`docs/PRINCIPLES.md` §4.1) — a download failure, an unavailable bench dispatcher, or a
    genuine bench failure are all a `TestResult` with `passed=False`, never a raise."""

    candidate: TestCandidate
    passed: bool
    started_at: datetime
    finished_at: datetime
    bench_summary: str = ""
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        """Whether this result is trustworthy at all — distinct from `passed`
        (`ok=False` means the test itself could not run; `passed=False` with `ok=True`
        means it ran and genuinely failed)."""
        return not self.error_code


@dataclass(frozen=True)
class TestHistoryEntry:
    """One row of `GetTestHistory` (§6) — `TestResult` plus the recording timestamp,
    since a result's own `finished_at` is when the *test* completed, not necessarily when
    it was durably recorded."""

    result: TestResult
    recorded_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class DownloadResult:
    """`download.py`'s own outcome — a real byte count and destination, or an error,
    never a raise (§4.1). `resumed` is `True` only when this attempt genuinely appended
    to an existing partial file after the server honored a `Range` request — a caller
    reporting download progress (Inference API's own provisioning stream, in particular)
    can tell a real resume apart from a fresh start rather than assuming one or the
    other."""

    ok: bool
    destination: str = ""
    bytes_written: int = 0
    resumed: bool = False
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class ProvingGroundsMetrics:
    """This sub-API's own counters, snapshotted (`metrics.py`)."""

    candidates_tested: int = 0
    candidates_passed: int = 0
    candidates_failed: int = 0
    downloads_succeeded: int = 0
    downloads_failed: int = 0
    promotions_gated_pass: int = 0
    promotions_gated_reject: int = 0

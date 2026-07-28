"""Content Security API error taxonomy.

These are surfaced as `error_code`/`rejection_reason` on `ScanVerdict`/`ContainerScanVerdict`
rather than raised across the gRPC boundary (`docs/PRINCIPLES.md` §4.1). The exception classes
below exist purely for the *internal* call path, where telling failure modes apart is genuinely
useful — `pipeline.py` reacts differently to "no provider is configured at all" than to "a
provider was invoked and it crashed," even though both end at the identical wire outcome,
`safe=False`.

**This package has no equivalent of Auth's raise-loudly carve-out, and it has no equivalent of
Logs'/Audit's "degrade gracefully, this can never fail the caller" posture either.** It sits
deliberately between them: `docs/PRINCIPLES.md` §4.2 names Content Security as the canonical
case of failing closed, which means every failure mode below is caught internally and turned
into data (never raised across the boundary, matching Logs/Audit) — but unlike Logs/Audit,
"turned into data" here always means "turned into a deny," never a routine drop or a quietly
degraded feature. A log entry that fails to write does not fail the run that was being logged;
a scan that fails to run *does* fail the file being scanned, and that is not a bug to route
around, it is the entire point of this API.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

# --------------------------------------------------------------------- wire codes
# Stable strings, added but never renamed or reused, the same discipline `.proto` field
# numbers and `core/audit`'s `ActionType` values already follow — a caller may be matching on
# one of these.

E_INVALID_REQUEST = "INVALID_REQUEST"
E_NOT_A_VALID_CONTAINER = "INVALID_CONTAINER"
E_ARCHIVE_BOMB = "ARCHIVE_BOMB_DETECTED"
E_POLYGLOT_DETECTED = "POLYGLOT_DETECTED"
E_NO_PROVIDER_AVAILABLE = "NO_SCAN_PROVIDER_AVAILABLE"
E_SCAN_PROVIDER_FAILED = "SCAN_PROVIDER_FAILED"
E_MALICIOUS_CONFIRMED = "MALICIOUS_CONFIRMED"
E_STAFF_REVIEW_REQUIRED = "STAFF_REVIEW_REQUIRED"
E_MEMBER_UNSAFE = "CONTAINER_MEMBER_UNSAFE"

#: Operator-facing one-liners, kept next to the codes so a client that only has the code still
#: has something to show (`docs/PRINCIPLES.md` §2.1.1 — a module-level lookup table nothing
#: should ever write is a `FrozenDict`, not a plain `dict`).
ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        E_INVALID_REQUEST: "the scan request carried no content to scan",
        E_NOT_A_VALID_CONTAINER: "the submitted file is not a readable archive",
        E_ARCHIVE_BOMB: "the archive's own metadata indicates a decompression bomb",
        E_POLYGLOT_DETECTED: "the file is valid as more than one format simultaneously",
        E_NO_PROVIDER_AVAILABLE: (
            "no malware scan provider is available; the file cannot be verified safe"
        ),
        E_SCAN_PROVIDER_FAILED: "a malware scan provider failed, crashed, or timed out",
        E_MALICIOUS_CONFIRMED: "every enabled scanner agreed this file is malicious",
        E_STAFF_REVIEW_REQUIRED: (
            "scan providers disagree or returned a low-confidence result; staff review "
            "required"
        ),
        E_MEMBER_UNSAFE: "one or more files extracted from this container failed their own scan",
    }
)


# ------------------------------------------------------------- internal types


class ContentSecurityError(Exception):
    """Base for everything this package raises internally. Never crosses a boundary — every
    call site that can raise one of these catches it and returns a `safe=False` verdict."""

    code: str = E_SCAN_PROVIDER_FAILED


class InvalidScanRequest(ContentSecurityError):
    """A request with no content, or content too large to reasonably hold in memory."""

    code = E_INVALID_REQUEST


class NotAValidContainer(ContentSecurityError):
    """`ScanContainer` was called with bytes `zipfile` cannot open at all."""

    code = E_NOT_A_VALID_CONTAINER


class ArchiveBombDetected(ContentSecurityError):
    """The container-level check (§3) rejected the archive before any extraction."""

    code = E_ARCHIVE_BOMB


class PolyglotDetected(ContentSecurityError):
    """The file matches more than one format's own magic bytes (§8)."""

    code = E_POLYGLOT_DETECTED


class NoProviderAvailable(ContentSecurityError):
    """Every registered `MalwareScanProvider.is_available()` returned False.

    This is the sharpest expression of §4.2 in this package: an *unavailable* security check
    is not a reason to skip the check, it is a reason to deny outright. Contrast with
    `docs/PRINCIPLES.md` §4.4's OCR example, where a missing engine degrades that one engine
    to unavailable and the run proceeds with whatever else is enabled — that graceful
    degradation is exactly what does *not* apply here, because there is nothing left to fall
    back to when the fallback itself is "did not check."
    """

    code = E_NO_PROVIDER_AVAILABLE


class ScanProviderFailed(ContentSecurityError):
    """A provider was available, was invoked, and its invocation itself failed — a crash, a
    timeout, or a malformed response it could not parse. Deliberately one exception type for
    all three: `pipeline.py`'s own resolution treats them identically (deny, no staff review,
    §4.2), and a caller reading `rejection_reason`/`detail` gets the specifics either way."""

    code = E_SCAN_PROVIDER_FAILED


#: Stable lookup from an internal exception's own type to its wire code — the analogue of
#: `core/logs`'s `ERROR_CODES`/`code_for()`. `FrozenDict` per §2.1.1.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        InvalidScanRequest: E_INVALID_REQUEST,
        NotAValidContainer: E_NOT_A_VALID_CONTAINER,
        ArchiveBombDetected: E_ARCHIVE_BOMB,
        PolyglotDetected: E_POLYGLOT_DETECTED,
        NoProviderAvailable: E_NO_PROVIDER_AVAILABLE,
        ScanProviderFailed: E_SCAN_PROVIDER_FAILED,
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or the base class's own fallback for anything
    unmapped — never an exception raised out of the error-handling path itself."""
    return ERROR_CODES.get(type(exc), ContentSecurityError.code)


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "E_ARCHIVE_BOMB",
    "E_INVALID_REQUEST",
    "E_MALICIOUS_CONFIRMED",
    "E_MEMBER_UNSAFE",
    "E_NOT_A_VALID_CONTAINER",
    "E_NO_PROVIDER_AVAILABLE",
    "E_POLYGLOT_DETECTED",
    "E_SCAN_PROVIDER_FAILED",
    "E_STAFF_REVIEW_REQUIRED",
    "ArchiveBombDetected",
    "ContentSecurityError",
    "InvalidScanRequest",
    "NoProviderAvailable",
    "NotAValidContainer",
    "PolyglotDetected",
    "ScanProviderFailed",
    "code_for",
]

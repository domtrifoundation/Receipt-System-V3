"""Update/Deployment API's error taxonomy.

Surfaced as `error_code`/`error_detail` on `ReleaseCloneResult` rather than raised across
this API's own boundary (`docs/PRINCIPLES.md` §4.1) — a failed clone is an ordinary,
expected outcome (a bad ref, a network blip, a Keymaster outage), never a reason to take
this whole service down.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class UpdateInternalError(Exception):
    """Base for everything this package raises internally, never across its boundary."""


class RefNotFound(UpdateInternalError):
    """Neither the requested channel's own tag/branch nor the `main` fallback could be
    resolved — a genuinely broken remote, not the ordinary pre-release-development case
    `installer/common.sh` already degrades gracefully (that one falls back to `main`)."""


class CloneFailed(UpdateInternalError):
    """`git clone` itself failed — a bad network, an invalid token, a corrupted remote."""


class VersionUnreadable(UpdateInternalError):
    """The freshly cloned `common/version.py` had no `PROGRAM_VERSION` line, or the clone's
    own `git rev-parse` failed — the clone exists on disk but cannot be named per
    `docs/MAINTENANCE.md` §2's `<version>_<commit-hash>` scheme."""


class FinalizeFailed(UpdateInternalError):
    """Setup API's own `finalize_clone()` reported `ok=False` — the clone is on disk but not
    eligible for Supervisor's Boot Sequence (strip, venv provisioning, or another finalize
    step failed)."""


ERROR_CODES: FrozenDict = FrozenDict(
    {
        RefNotFound: "REF_NOT_FOUND",
        CloneFailed: "CLONE_FAILED",
        VersionUnreadable: "VERSION_UNREADABLE",
        FinalizeFailed: "FINALIZE_FAILED",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "REF_NOT_FOUND": "Neither the requested channel nor the main fallback could be resolved.",
        "CLONE_FAILED": "git clone itself failed.",
        "VERSION_UNREADABLE": "The freshly cloned directory could not be named — version or commit hash unreadable.",
        "FINALIZE_FAILED": "The clone is on disk but failed Setup API's own finalize routine.",
        "INTERNAL": "An unmapped internal error.",
    }
)


def code_for(exc: BaseException) -> str:
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    return ERROR_SUMMARIES.get(code, ERROR_SUMMARIES["INTERNAL"])


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "CloneFailed",
    "FinalizeFailed",
    "RefNotFound",
    "UpdateInternalError",
    "VersionUnreadable",
    "code_for",
    "summary_for",
]

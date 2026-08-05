"""Setup API's error taxonomy.

Errors are data at this API's boundaries (`docs/PRINCIPLES.md` §4.1) — these types are carried
in a result object's `error` field, never raised across a gRPC boundary. Setup has no equivalent
of Auth's deliberate raise-loudly carve-out: a failure here happens during install or update,
where the caller is a bootstrap script or Update API's `release_manager.py` deciding whether the
clone is salvageable, and an exception denies that caller every outcome after the first bad one.

Provisioning's own error type lives in `contracts.py` alongside the rest of that surface
(`ProvisionError`), because it is part of a contract other packages import. What lives here is
what Setup's own internals report among themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["StripError", "StripErrorCode"]


class StripErrorCode(str, Enum):
    """Why `strip_development_content()` could not remove something it was asked to remove.

    Distinct codes because the operator response genuinely differs: a permission failure on
    Windows usually means the file is open in an editor or held by a running process and is
    worth retrying, whereas an escape attempt means the input was malformed and retrying is
    exactly the wrong response.
    """

    REMOVAL_FAILED = "removal_failed"
    """The entry existed and could not be deleted — permissions, a lock, a read-only file."""

    PATH_ESCAPES_CLONE = "path_escapes_clone"
    """A resolved path landed outside the clone directory.

    Deliberately its own code rather than folded into a generic failure. This function deletes
    directory trees, and the top-level installation directory — holding config, user data and
    model weights — is a *sibling* of every release clone (`docs/PRINCIPLES.md` §1.6). An escape
    here is the difference between removing `docs/` and removing a user's receipts, so it is
    refused and reported rather than attempted.
    """


@dataclass(frozen=True)
class StripError:
    code: StripErrorCode

    entry: str
    """The offending entry, relative to the clone root — enough to act on, without a full path
    that may contain a user's own directory names."""

    detail: str
    """The real underlying message, not a paraphrase (`v3-plan-04-v2-audit-findings.md`'s
    `str(e)`-instead-of-full-traceback finding, applied here)."""

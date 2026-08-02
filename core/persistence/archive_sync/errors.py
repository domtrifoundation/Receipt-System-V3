"""Archive Sync error codes."""

from __future__ import annotations

TARGET_UNREACHABLE = "sync_target_unreachable"
TARGET_MISSING = "sync_target_missing"
CREDENTIAL_MISSING = "sync_credential_missing"
CREDENTIAL_SCOPE_INSUFFICIENT = "sync_credential_scope_insufficient"
UPLOAD_FAILED = "sync_upload_failed"
UNKNOWN_PROVIDER = "sync_unknown_provider"
SYNC_PAUSED = "sync_paused"


class ArchiveSyncError(Exception):
    code = UPLOAD_FAILED


class CredentialScopeInsufficient(ArchiveSyncError):
    """The reused ingestion grant is read-only and the outbound direction needs write.

    Checked explicitly rather than assumed: credential reuse only works cleanly when the
    granted scope already covers write access to the target folder, and discovering that it
    does not by watching an upload fail is a worse answer than saying so up front (§3).
    """

    code = CREDENTIAL_SCOPE_INSUFFICIENT


__all__ = [
    "CREDENTIAL_MISSING",
    "CREDENTIAL_SCOPE_INSUFFICIENT",
    "SYNC_PAUSED",
    "TARGET_MISSING",
    "TARGET_UNREACHABLE",
    "UNKNOWN_PROVIDER",
    "UPLOAD_FAILED",
    "ArchiveSyncError",
    "CredentialScopeInsufficient",
]

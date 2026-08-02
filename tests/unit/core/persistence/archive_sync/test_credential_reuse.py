"""One authorization, not two — and the scope check that is explicit rather than assumed."""

from __future__ import annotations

from core.persistence.archive_sync.credential_reuse import (
    DRIVE_WRITE_SCOPE,
    DriveGrant,
    resolve_outbound_grant,
)
from core.persistence.archive_sync.errors import (
    CREDENTIAL_MISSING,
    CREDENTIAL_SCOPE_INSUFFICIENT,
)

from ..conftest import run


class _Source:
    def __init__(self, grant):
        self._grant = grant

    async def get_drive_grant(self, user_id):
        return self._grant


def test_a_write_capable_ingestion_grant_is_reused():
    grant = DriveGrant("user-1", "google_drive", (DRIVE_WRITE_SCOPE,), "token-ref")
    check = run(resolve_outbound_grant(_Source(grant), "user-1"))
    assert check.ok
    assert check.grant is grant


def test_a_read_only_grant_needs_its_own_authorization():
    """Checked up front, not discovered when an upload fails halfway through a pass."""
    grant = DriveGrant(
        "user-1", "google_drive", ("https://www.googleapis.com/auth/drive.readonly",), "t"
    )
    check = run(resolve_outbound_grant(_Source(grant), "user-1"))
    assert not check.ok
    assert check.error_code == CREDENTIAL_SCOPE_INSUFFICIENT
    assert check.grant is grant, "the caller still needs to know which grant fell short"


def test_no_grant_at_all_is_a_distinct_answer():
    check = run(resolve_outbound_grant(_Source(None), "user-1"))
    assert check.error_code == CREDENTIAL_MISSING


def test_no_configured_source_is_reported_rather_than_assumed():
    check = run(resolve_outbound_grant(None, "user-1"))
    assert check.error_code == CREDENTIAL_MISSING

"""Reusing the Drive grant a user already gave for ingestion (§3).

**One authorization, not two.** Where a user already granted Drive access for *ingestion*,
the outbound direction reuses that same connection rather than asking them to authorize a
second time. Ingestion's own swappable credential-strategy pattern is what is being reused
here — this module is the seam onto it, not a second credential mechanism.

**The scope check is explicit, not assumed.** Reuse only works cleanly when the granted scope
already covers write access to the target folder. A read-only ingestion grant genuinely does
need its own separate authorization for the outbound direction, and saying so up front is
better than discovering it when an upload fails halfway through a mirror pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import CREDENTIAL_MISSING, CREDENTIAL_SCOPE_INSUFFICIENT

#: The Drive scope that permits writing into a folder. Named once here so the check and any
#: future re-authorization prompt agree on what is actually being asked for.
DRIVE_WRITE_SCOPE = "https://www.googleapis.com/auth/drive.file"


@dataclass(frozen=True)
class DriveGrant:
    """What Ingestion's credential store hands back for a user."""

    user_id: str
    provider_name: str
    scopes: tuple[str, ...]
    token_ref: str

    def covers_write(self) -> bool:
        return DRIVE_WRITE_SCOPE in self.scopes


@dataclass(frozen=True)
class CredentialCheck:
    ok: bool
    grant: DriveGrant | None = None
    error_code: str = ""
    error_detail: str = ""


class IngestionCredentialSource(Protocol):
    """Ingestion API's own credential strategy, behind one interface (§1.3)."""

    async def get_drive_grant(self, user_id: str) -> DriveGrant | None: ...


async def resolve_outbound_grant(
    source: IngestionCredentialSource | None, user_id: str
) -> CredentialCheck:
    """Reuse the ingestion grant if it covers write; say so plainly if it does not."""
    if source is None:
        return CredentialCheck(
            ok=False,
            error_code=CREDENTIAL_MISSING,
            error_detail="no ingestion credential source is configured",
        )
    grant = await source.get_drive_grant(user_id)
    if grant is None:
        return CredentialCheck(
            ok=False,
            error_code=CREDENTIAL_MISSING,
            error_detail=f"user {user_id} has no Drive grant to reuse",
        )
    if not grant.covers_write():
        return CredentialCheck(
            ok=False,
            grant=grant,
            error_code=CREDENTIAL_SCOPE_INSUFFICIENT,
            error_detail=(
                "the existing ingestion grant is read-only; the outbound direction needs a "
                "separate authorization covering write access to the target folder"
            ),
        )
    return CredentialCheck(ok=True, grant=grant)


__all__ = [
    "DRIVE_WRITE_SCOPE",
    "CredentialCheck",
    "DriveGrant",
    "IngestionCredentialSource",
    "resolve_outbound_grant",
]

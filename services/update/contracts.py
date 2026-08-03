"""Update/Deployment API's data contracts — types only, no logic (`docs/PRINCIPLES.md` §1.1).

**Scoped narrowly, deliberately.** This session builds only what the release/installer pipeline
needs: `ChannelName` (the four user-selectable channels plus the owner-only Latest-Commit one,
`v3-deepdive-24-update-deployment-api.md` §2's own `contracts.py` line names `Channel`) and
Keymaster's own client-side contracts (§4). `ReleaseDirectory` and the rest of §2's sketch arrive
with `release_manager.py`, which is not part of this session's scope.

**Keymaster is a completely separate, closed external system, not part of this repo**
(`v3-plan-02-architecture.md`: "licensing lives entirely outside the `receipt-system-v3`
codebase, in its own separate repo DOMTRI alone deploys, whose source never reaches a customer's
machine"). What lives here is the *client* — an outbound HTTPS call, "the same category as
calling PayMongo/GitHub/LocationIQ" (§4) — never Keymaster's own validation logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

__all__ = [
    "ChannelName",
    "KeymasterRejectionReason",
    "KeymasterResult",
    "KeymasterToken",
]


class ChannelName(str, Enum):
    """`docs/MAINTENANCE.md` §2: "Four channels: LTSC, Stable, Beta, Alpha (user-selectable),
    plus an owner-only Latest-Commit channel." LTSC is a real git branch; Stable/Beta/Alpha are
    tags "promoted forward over time" — force-moved to point at a newer commit as promotion
    happens, not per-version immutable tags (those are the separate `x03.xx.xx` release tags).
    """

    LTSC = "ltsc"
    STABLE = "stable"
    BETA = "beta"
    ALPHA = "alpha"
    LATEST_COMMIT = "latest_commit"


class KeymasterRejectionReason(str, Enum):
    """Why `KeymasterClient.get_scoped_clone_token()` did not return a usable token.

    Distinct local-observation reasons, not a wire-level distinction — §4's "every failure mode
    (wrong key, unactivated, expired) returns an identical generic rejection" is a constraint on
    what *Keymaster's own server* tells a caller (so a would-be attacker probing a guessed key
    learns nothing), not a constraint on what this client may record about its own request.
    `SERVER_REJECTED` is exactly that one generic bucket every server-side rejection collapses
    into, on this client's own side, honoring the real constraint. `NO_KEY_CONFIGURED` and
    `NETWORK_UNREACHABLE` are genuinely different situations an operator's own logs benefit from
    telling apart, and are never sent anywhere Keymaster or an attacker could observe.
    """

    NO_KEY_CONFIGURED = "no_key_configured"
    NETWORK_UNREACHABLE = "network_unreachable"
    SERVER_REJECTED = "server_rejected"
    MALFORMED_RESPONSE = "malformed_response"


@dataclass(frozen=True)
class KeymasterToken:
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class KeymasterResult:
    """Errors are data (`docs/PRINCIPLES.md` §4.1) — `get_scoped_clone_token()` returns this
    rather than raising, matching §4's own "fail-open, always": a Keymaster outage or rejection
    must never itself crash the caller. What happens next (proceed unauthenticated against a
    public repo, or refuse against a private one) is the caller's own policy decision, not
    something this type or this client encodes."""

    token: KeymasterToken | None = None
    rejection: KeymasterRejectionReason | None = None

    @property
    def ok(self) -> bool:
        return self.token is not None

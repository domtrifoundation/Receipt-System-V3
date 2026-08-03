"""Update/Deployment API's data contracts — types only, no logic (`docs/PRINCIPLES.md` §1.1).

**`ReleaseDirectory`/`ReleaseCloneResult` arrive this session, alongside `release_manager.py`.**
The wire shape matches `installer/common.sh`'s own real, live-tested clone flow exactly — that
shell script is the pre-Python reference implementation of this same operation and the two must
never drift (see `release_manager.py`'s own module docstring).

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
from pathlib import Path

from services.setup.contracts import BootstrapReport

__all__ = [
    "ChannelName",
    "ChannelUsage",
    "KeymasterRejectionReason",
    "KeymasterResult",
    "KeymasterToken",
    "ReleaseCloneResult",
    "ReleaseDirectory",
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
class ReleaseDirectory:
    """One cloned, named release directory (`<version>_<commit-hash>`, `docs/MAINTENANCE.md`
    §2) — the unit Update API produces and Supervisor's Boot Sequence launches from.

    `path` is the real filesystem location; every other field is read out of the fresh clone
    itself (`common/version.py`'s `PROGRAM_VERSION`, `git rev-parse --short HEAD`) rather than
    guessed, matching `installer/common.sh`'s own live-tested "whatever that ref actually
    contains, not whatever this installer script happened to ship with."
    """

    path: Path
    version: str
    commit_hash: str
    ref: str
    channel: ChannelName


@dataclass(frozen=True)
class ReleaseCloneResult:
    """The outcome of one `clone_release()` call. Errors are data (`docs/PRINCIPLES.md` §4.1)
    — a failed clone or a failed finalize both come back here, never raised.
    """

    ok: bool
    release: ReleaseDirectory | None = None
    finalize: BootstrapReport | None = None
    used_fallback_ref: bool = False
    """True when the requested channel had no tag/branch yet and this clone fell back to
    `main` — `installer/common.sh`'s own real behaviour during pre-release development
    (`docs/MAINTENANCE.md` §2: "this project is still in pre-release development")."""
    keymaster_token_used: bool = False
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class ChannelUsage:
    """One channel's own recorded clone history (`GetActiveChannels`) — "which channels
    have configured/active usage," distinct from Supervisor's own `GetActiveRelease`
    ("which specific directory is live for a channel right now"). Derived from this
    module's own real clone activity (`release_manager.record_channel_usage`), not from a
    separate, not-yet-built per-user channel-selection config — see `release_manager.py`'s
    own docstring for the honest scope of what this actually answers.
    """

    channel: ChannelName
    last_release_name: str
    last_cloned_at: datetime


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

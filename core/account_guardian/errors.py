"""Account Guardian error taxonomy.

These are surfaced as the `error`/`error_detail` pair on the result types in `contracts.py`,
and as `error_code`/`error_detail` on the wire — never raised across the gRPC boundary
(`docs/PRINCIPLES.md` §4.1). This package has no carve-out of its own; the exception classes
below are for the *internal* call path only, caught before they reach a boundary, the same
shape `core/logs/errors.py` and `core/audit/errors.py` both use.

**The one raised exception this package's *callers* will see is not defined here at all.**
When a session cannot be resolved, this API asks Auth to resolve it and lets Auth's own
`core.auth.errors.SessionInvalid` / `SessionExpired` / `RoleInsufficient` propagate unchanged
(`gateways.py`) — the deliberate, documented carve-out belongs to Auth
(`docs/PRINCIPLES.md` §4.1), and Account Guardian's job is to *not* swallow it into a result
field, which would be exactly the "caller silently ignores an auth failure" failure mode the
carve-out exists to prevent. Re-declaring a parallel `AccountGuardianSessionInvalid` here
would be inventing a third convention where the task is to reuse the existing one.

**Fail-closed is a data value here, not a raise.** `docs/PRINCIPLES.md` §4.2 says an
unresolvable security check must deny, never silently permit — but "deny" is still an
ordinary `.error`-carrying result for every check this package owns itself (ownership,
verification sufficiency, consent). Only Auth's own session/role resolution gets the raise;
everything downstream of a *resolved* session is data, exactly like Audit's `RoleForbidden`.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

# --------------------------------------------------------------- wire codes
# Stable strings, added and never renamed or reused — a caller may be branching on one.

E_OWNERSHIP_DENIED = "OWNERSHIP_DENIED"
E_NOT_FOUND = "NOT_FOUND"
E_INVALID_REQUEST = "INVALID_REQUEST"
E_INVALID_STAGE_TRANSITION = "INVALID_STAGE_TRANSITION"
E_ALREADY_RESOLVED = "ALREADY_RESOLVED"
E_VERIFICATION_INSUFFICIENT = "VERIFICATION_INSUFFICIENT"
E_UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
E_CAPABILITY_MISSING = "CAPABILITY_MISSING"
E_DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
E_RECONSENT_REQUIRED = "RECONSENT_REQUIRED"
E_WRITE_FAILED = "WRITE_FAILED"

#: Operator-facing one-liners, kept next to the codes so a client that only has the code
#: still has something to show (`docs/PRINCIPLES.md` §2.1.1 — a module-level lookup table
#: nothing should ever write is a `FrozenDict`, same as `core/audit/errors.py`).
ERROR_SUMMARIES: FrozenDict = FrozenDict({
    E_OWNERSHIP_DENIED: "this device, request, or link does not belong to the caller's own account",
    E_NOT_FOUND: "no matching request exists",
    E_INVALID_REQUEST: "the request is missing a required field or value",
    E_INVALID_STAGE_TRANSITION: "this request cannot move to the requested stage from its current one",
    E_ALREADY_RESOLVED: "this request has already reached a terminal stage",
    E_VERIFICATION_INSUFFICIENT: "no recovery verification check has been satisfied yet",
    E_UNSUPPORTED_PROVIDER: "this SSO provider is not one Auth & Tenancy can authenticate against",
    E_CAPABILITY_MISSING: (
        "the dependency this action needs has not yet exposed the capability it requires "
        "— see this package's CLAUDE.md for the specific gap"
    ),
    E_DEPENDENCY_UNAVAILABLE: (
        "the required dependency could not be reached; the action was not performed, "
        "never silently skipped"
    ),
    E_RECONSENT_REQUIRED: "the caller must accept the current policy version before continuing",
    E_WRITE_FAILED: "the request could not be recorded",
})


# ------------------------------------------------------------- internal types


class AccountGuardianError(Exception):
    """Base for everything this package raises internally. Never crosses a boundary."""

    code: str = E_WRITE_FAILED


class OwnershipDenied(AccountGuardianError):
    """A caller tried to act on a device, case, or link that is not their own.

    Fails closed by construction: `devices.py`, `account_recovery.py` and `sso_linking.py`
    each resolve the target's real owner from storage or from Auth before acting, and this
    is what they raise internally when it does not match the acting `user_id`
    (`docs/PRINCIPLES.md` §4.2) — never inferred from a caller-supplied field alone.
    """

    code = E_OWNERSHIP_DENIED


class NotFound(AccountGuardianError):
    code = E_NOT_FOUND


class InvalidRequest(AccountGuardianError):
    code = E_INVALID_REQUEST


class InvalidStageTransition(AccountGuardianError):
    """An attempted state-machine transition this package's own rules do not allow — e.g.
    cancelling a deletion once `PROCESSING` has started (deep-dive §6.3: "genuinely
    irreversible and this call correctly fails rather than pretending to succeed")."""

    code = E_INVALID_STAGE_TRANSITION


class AlreadyResolved(AccountGuardianError):
    code = E_ALREADY_RESOLVED


class VerificationInsufficient(AccountGuardianError):
    """An attempt to approve a recovery request whose checklist has no check satisfied at
    all (`contracts.RecoveryVerificationChecklist.any_check_satisfied`)."""

    code = E_VERIFICATION_INSUFFICIENT


class UnsupportedProvider(AccountGuardianError):
    code = E_UNSUPPORTED_PROVIDER


class CapabilityMissing(AccountGuardianError):
    """A dependency this action needs has not exposed the RPC/mechanism it requires yet.

    Real, current instances, each documented at the raise site in `gateways.py` rather than
    only here: Auth's `AuthService` has no session-listing RPC; Persistence has not yet
    generated a gRPC servicer for `persistence.proto` at all; Billing API does not exist in
    this build. Each is a genuine cross-API gap, not a bug in this package — raised so the
    caller degrades (`docs/PRINCIPLES.md` §4.4) rather than silently pretending the action
    succeeded.
    """

    code = E_CAPABILITY_MISSING


class DependencyUnavailable(AccountGuardianError):
    """A transport-level failure talking to a real dependency (Auth, Persistence, Billing)
    — distinct from `CapabilityMissing`, which means the RPC does not exist yet at all.

    This is the deep-dive's own named testing hook (§11): "a session revocation call during
    Auth's `SessionStore` being briefly unavailable" must surface as a clean, visible
    failure, never a silent no-op that leaves a caller believing a device was logged out
    when it was not.
    """

    code = E_DEPENDENCY_UNAVAILABLE


class ReconsentRequired(AccountGuardianError):
    """§7.4's enforcement gate. Internal only — `service.py` turns this into a data result
    on every RPC except the two policy/consent RPCs themselves, which must remain reachable
    or a blocked caller could never clear the gate."""

    code = E_RECONSENT_REQUIRED


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, defaulting to the exception's own `code`
    attribute, or `WRITE_FAILED` for anything unmapped. Unlike `core/logs/errors.py`'s
    lookup table, every exception here already carries its own code as a class attribute —
    a second table mapping type to string would be a second place for the two to drift.
    """
    return getattr(exc, "code", E_WRITE_FAILED)


__all__ = [
    "AccountGuardianError",
    "AlreadyResolved",
    "CapabilityMissing",
    "DependencyUnavailable",
    "ERROR_SUMMARIES",
    "E_ALREADY_RESOLVED",
    "E_CAPABILITY_MISSING",
    "E_DEPENDENCY_UNAVAILABLE",
    "E_INVALID_REQUEST",
    "E_INVALID_STAGE_TRANSITION",
    "E_NOT_FOUND",
    "E_OWNERSHIP_DENIED",
    "E_RECONSENT_REQUIRED",
    "E_UNSUPPORTED_PROVIDER",
    "E_VERIFICATION_INSUFFICIENT",
    "E_WRITE_FAILED",
    "InvalidRequest",
    "InvalidStageTransition",
    "NotFound",
    "OwnershipDenied",
    "ReconsentRequired",
    "UnsupportedProvider",
    "VerificationInsufficient",
    "code_for",
]

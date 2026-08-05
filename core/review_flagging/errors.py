"""Review/Flagging API error taxonomy, in `core/logs/errors.py`'s own shape.

These are surfaced as `error_code`/`error_detail` on the result contracts rather than raised
across the API boundary (`docs/PRINCIPLES.md` §4.1). They exist as real types because the
*internal* call path still benefits from telling them apart — a flag nobody can find and a
staff member denied the wrong role are different operator problems with different fixes.

This API has no equivalent of Auth's raise-loudly carve-out: nothing here is a session
failure, and a flag lifecycle whose own failure took the caller down would be strictly worse
than reporting the refusal as data. The one place this package is deliberately *not*
graceful is the staff/owner role gate on assignment, resolution and dismissal — an
unresolvable session or an insufficient role is denied, never defaulted to permitted
(`docs/PRINCIPLES.md` §4.2). Everything else — an unrecognised `flag_type`, an unreachable
Logs trace source, an unwired Persistence write gateway — degrades gracefully (§4.4).
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class ReviewFlaggingError(Exception):
    """Base for everything this API raises internally, never across its boundary."""


class UnknownFlag(ReviewFlaggingError):
    """An assign/resolve/dismiss/lookup naming a flag id this store has no record of."""


class InvalidFlagRequest(ReviewFlaggingError):
    """A `CreateFlagRequest` missing a required field — empty `receipt_id`, `user_id`,
    `flag_type`, or `created_by`. Structural only: whether the *flag_type* is one Architect's
    registry actually recognises is a separate, non-fatal question (§4.4), not this one."""


class InvalidStageTransition(ReviewFlaggingError):
    """A transition `contracts.VALID_TRANSITIONS` does not permit from the flag's current
    status — resolving an already-`RESOLVED` flag, dismissing an already-`DISMISSED` one, or
    any attempt against a terminal state. Rejected explicitly, never silently no-op'd: a
    caller believing a second resolution attempt did something when it did not would be
    exactly the kind of silent, unaccountable state the state-machine discipline exists to
    prevent (mirrors `core/account_guardian/privacy/`'s own `InvalidStageTransition`)."""


class RoleForbidden(ReviewFlaggingError):
    """The resolved caller role is not `staff` or `owner` — including the case where no
    role could be resolved at all (`docs/PRINCIPLES.md` §4.2, fail closed). A `client`-role
    caller, or an unresolvable session, are both denied identically; only the audit trail
    tells the two apart."""


class OwnershipDenied(ReviewFlaggingError):
    """The flag is `ASSIGNED` to a different staff member and the acting caller is not the
    `owner` role (§8's own resolved routing policy: "any staff member can self-assign, an
    owner can reassign" — the reverse of that is that a *non*-owner staff member cannot act
    on someone else's assignment)."""


class StoreUnavailable(ReviewFlaggingError):
    """The flag store's own backing SQLite database could not be opened or written."""


class EditWriteFailed(ReviewFlaggingError):
    """A resolution's own data-change edit could not be written through Persistence's
    normal write path (§4). The flag stays exactly where it was — never marked `RESOLVED`
    on the strength of a write that did not actually happen, which is the "never a special-
    cased bypass" guarantee `docs/PRINCIPLES.md` §4.3 asks for applied to this lifecycle."""


#: Stable wire codes for the `.proto` surface's own `error_code` fields. Field-only-append
#: discipline applies here the same way it does to the `.proto`: a code is added, never
#: renamed, because a client may be matching on it.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        UnknownFlag: "UNKNOWN_FLAG",
        InvalidFlagRequest: "INVALID_FLAG_REQUEST",
        InvalidStageTransition: "INVALID_STAGE_TRANSITION",
        RoleForbidden: "ROLE_FORBIDDEN",
        OwnershipDenied: "OWNERSHIP_DENIED",
        StoreUnavailable: "STORE_UNAVAILABLE",
        EditWriteFailed: "EDIT_WRITE_FAILED",
    }
)

#: One-line operator-facing summaries, keyed by wire code. Kept beside the codes so a caller
#: rendering an error never has to invent its own wording for a condition this API named.
ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "UNKNOWN_FLAG": "no flag exists with that id.",
        "INVALID_FLAG_REQUEST": "the flag creation request was missing a required field.",
        "INVALID_STAGE_TRANSITION": (
            "that transition is not valid from the flag's current status; a resolved or "
            "dismissed flag cannot be resolved or dismissed again."
        ),
        "ROLE_FORBIDDEN": (
            "resolving, dismissing or assigning a flag requires a staff or owner role, "
            "resolved from the caller's own session."
        ),
        "OWNERSHIP_DENIED": (
            "this flag is assigned to a different staff member; only its assignee or an "
            "owner may act on it."
        ),
        "STORE_UNAVAILABLE": "the flag store could not be reached.",
        "EDIT_WRITE_FAILED": (
            "the resolution's own edit could not be written through Persistence's normal "
            "write path; the flag was left unchanged."
        ),
        "INTERNAL": "an unmapped internal error.",
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped.

    Unmapped is deliberately not an exception of its own: a caller receiving `INTERNAL` with
    a real detail string is strictly better off than one receiving a crash from the error
    path itself.
    """
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    """The operator-facing summary for a wire code, or a generic line for an unknown one."""
    return ERROR_SUMMARIES.get(code, ERROR_SUMMARIES["INTERNAL"])


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "EditWriteFailed",
    "InvalidFlagRequest",
    "InvalidStageTransition",
    "OwnershipDenied",
    "ReviewFlaggingError",
    "RoleForbidden",
    "StoreUnavailable",
    "UnknownFlag",
    "code_for",
    "summary_for",
]

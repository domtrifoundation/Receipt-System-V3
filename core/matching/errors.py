"""Matching API error taxonomy.

These are surfaced as `MatchError.code`/`.detail` on the result contracts and on the wire's
`error_code`/`error_detail` fields, never raised across the gRPC boundary
(`docs/PRINCIPLES.md` §4.1). Matching has no equivalent of Auth's raise-loudly carve-out —
nothing here is a security decision, and a caller that got no match this run is strictly
better served by a low-confidence (or empty) `MatchResult` than by an exception.

**An empty candidate list, a zero-scoring match, and a genuinely low-confidence top candidate
are not errors, and none of them are in here.** All three are ordinary, honest answers
(`docs/PRINCIPLES.md` §4.4) — "no candidates supplied," "nothing scored above zero," and
"the top score is low" are each represented as data on `MatchResult`/`MatchContext`, not as a
raised condition. This module is only for the case Matching genuinely cannot evaluate at all:
a request with nothing to search for, or a policy value it does not recognise.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class MatchingError(Exception):
    """Base for everything this package raises internally, never across its boundary."""


class InvalidMatchRequest(MatchingError):
    """A request with nothing to match: both `extracted_text` and `raw_ocr_text` are empty.

    An empty `candidates` tuple is deliberately *not* this — it is a legitimate "nothing to
    search against yet" answer (`docs/PRINCIPLES.md` §4.4). This is the narrower case where
    there is not even a string to search *with*.
    """


class InvalidCorroborationPolicy(MatchingError):
    """A `VendorCorroborationPolicy` wire value this API does not recognise (§5.2).

    Never guessed at or silently defaulted to `ALWAYS` — an unrecognised policy string is
    exactly the kind of ambiguity `docs/PRINCIPLES.md` §4.3 says gets surfaced, not resolved
    quietly in one direction.
    """


#: Stable wire codes for `matching.proto`'s own `error_code` fields. Field-only-append
#: discipline applies here the same way it does to the `.proto` itself: a code is added,
#: never renamed, because a client may be matching on it.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        InvalidMatchRequest: "INVALID_MATCH_REQUEST",
        InvalidCorroborationPolicy: "INVALID_CORROBORATION_POLICY",
    }
)

#: Operator-facing one-liners, keyed by wire code so a caller holding only a `MatchError.code`
#: string still has something to show. `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1.
ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "INVALID_MATCH_REQUEST": (
            "the match request had no extracted text and no raw OCR text to search with"
        ),
        "INVALID_CORROBORATION_POLICY": "the vendor corroboration policy value was not recognised",
        "INTERNAL": "An unmapped internal error.",
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
    "InvalidCorroborationPolicy",
    "InvalidMatchRequest",
    "MatchingError",
    "code_for",
    "summary_for",
]

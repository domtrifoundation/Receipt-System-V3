"""Architect error codes and internal exception types.

Two layers, deliberately: `ErrorCode` holds the stable strings that travel in an
`ArchitectError.code` and in `architect.proto`'s `error_code` field, and the exception
classes below exist for the *internal* call path only. Nothing here is ever raised across
an API boundary — a caller checks `result.error`, never wraps a call in try/except
(`docs/PRINCIPLES.md` §4.1). Architect has no equivalent of Auth's deliberate
raise-loudly exception: none of its failures are security decisions.

The codes are grouped by what a caller can actually do about them, which is the only
grouping that earns its keep — an unknown definition is a caller bug, a rejected
registration is a policy outcome, an unavailable seed source is neither.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class ErrorCode:
    """Stable, machine-readable error codes. Values are never reused for a new meaning."""

    # Caller supplied something the registry cannot resolve.
    UNKNOWN_DEFINITION = "unknown_definition"
    UNKNOWN_KIND = "unknown_kind"
    UNKNOWN_CORPORATION = "unknown_corporation"

    # Caller supplied something the registry refuses to accept.
    DUPLICATE_DEFINITION = "duplicate_definition"
    INVALID_DEFINITION = "invalid_definition"
    INVALID_PARENT = "invalid_parent"
    RESERVED_KIND = "reserved_kind"

    # The request was well-formed and something outside this API could not serve it.
    SEED_SOURCE_UNAVAILABLE = "seed_source_unavailable"
    SEED_SOURCE_FAILED = "seed_source_failed"


#: Default human-readable text per code, for a caller that has nothing better to show.
#: `FrozenDict` because it is a module-level constant lookup table read from several
#: threads and never written (`docs/PRINCIPLES.md` §2.1.1) — the free-threading target is
#: exactly why "nobody would mutate this" is not a good enough guarantee.
ERROR_MESSAGES = FrozenDict(
    {
        ErrorCode.UNKNOWN_DEFINITION: "no definition is registered under that code",
        ErrorCode.UNKNOWN_KIND: "not a definition kind this registry defines",
        ErrorCode.UNKNOWN_CORPORATION: "no corporation with that id is visible to you",
        ErrorCode.DUPLICATE_DEFINITION: "a definition is already registered under that code",
        ErrorCode.INVALID_DEFINITION: "the definition is malformed",
        ErrorCode.INVALID_PARENT: "the parent code does not resolve to a registered category",
        ErrorCode.RESERVED_KIND: "new definition kinds go through the taxonomy-type template",
        ErrorCode.SEED_SOURCE_UNAVAILABLE: "the seed source is not reachable right now",
        ErrorCode.SEED_SOURCE_FAILED: "the seed source responded with something unusable",
    }
)


def message_for(code: str) -> str:
    """Default text for a code, or the code itself when it has no registered text."""
    return ERROR_MESSAGES.get(code, code)


class ArchitectInternalError(Exception):
    """Base for everything this package raises *internally*, never across a boundary."""


class UnknownDefinition(ArchitectInternalError):
    """A lookup found nothing under the requested code."""


class DuplicateDefinition(ArchitectInternalError):
    """A registration collided with an existing code of the same kind."""


class InvalidDefinition(ArchitectInternalError):
    """A registration was malformed — empty code, unknown parent, wrong kind for its type."""


class SeedSourceUnavailable(ArchitectInternalError):
    """A vendor-directory seed source cannot be reached.

    Raised inside the adapter and converted to a `BootstrapResult.degraded_reason` at the
    boundary: an unreachable public endpoint is a normal operating condition for a monthly
    poll, not a run failure (`docs/PRINCIPLES.md` §4.4).
    """


__all__ = [
    "ERROR_MESSAGES",
    "ArchitectInternalError",
    "DuplicateDefinition",
    "ErrorCode",
    "InvalidDefinition",
    "SeedSourceUnavailable",
    "UnknownDefinition",
    "message_for",
]

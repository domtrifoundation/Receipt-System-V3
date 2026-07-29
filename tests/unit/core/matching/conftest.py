"""Shared fixtures for Matching API's unit tests.

**No test in this package touches the network or a running Architect process.** Every
`VendorCandidate` is hand-built in memory — Matching consumes whatever candidate list a caller
already resolved from Architect's directory, and none of that resolution needs to be real for
these tests to be meaningful (`docs/apis/v3-deepdive-15-matching-api.md` §1).
"""

from __future__ import annotations

from core.matching.contracts import VendorCandidate


def make_candidate(
    entity_id: str,
    name: str,
    *,
    entity_kind: str = "corporation",
    tin: str = "",
    category_code: str | None = None,
    aliases: tuple[str, ...] = (),
) -> VendorCandidate:
    """A small builder so every test doesn't restate every `VendorCandidate` field."""
    return VendorCandidate(
        entity_id=entity_id,
        name=name,
        entity_kind=entity_kind,
        tin=tin,
        category_code=category_code,
        aliases=aliases,
    )


__all__ = ["make_candidate"]

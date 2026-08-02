"""The three-way resolution algorithm (`v3-deepdive-30-reimport.md` §4) — resolved policy.

Borrowed shape, deliberately: this is the same three-way merge version control systems use
for exactly this class of problem — a base snapshot plus two independent sets of changes
since. The three rules are the whole design and none of them may be softened:

1. **The user did not touch it** → canonical's own newer value wins. A stale local export
   must never be able to silently revert a real correction just because the user's copy
   predates it.
2. **Only the user touched it** → apply cleanly.
3. **Both touched it, to different values** → a genuine conflict. Canonical stays
   authoritative *until a human resolves it*, and the conflict is surfaced, never guessed
   at. There is no automatic last-write-wins here and no rejecting a whole reimport over one
   conflicting field (`docs/PRINCIPLES.md` §4.3).

The pure function below is deliberately free of I/O and of any Review/Flagging dependency,
so the resolution matrix test can exercise every combination directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from common.frozen_dict import FrozenDict

from .contracts import FieldConflict, ResolutionOutcome


def three_way_resolve(
    original: Mapping[str, Any],
    canonical: Mapping[str, Any],
    reimported: Mapping[str, Any],
    *,
    receipt_id: str = "",
) -> ResolutionOutcome:
    """Resolve one receipt's fields.

    All three arguments are typed and checked as `Mapping`, never as `dict`: they arrive as
    `FrozenDict` and the 3.15 builtin is not a `dict` subclass, so an `isinstance(x, dict)`
    gate would silently reject every real call (`docs/PRINCIPLES.md` §2.1).

    Iterates the *reimported* keys only. A field the user's file does not carry is a field
    the user had no opportunity to change, so canonical's value stands untouched — that is
    not the same as the user asking to clear it.
    """
    for name, value in (("original", original), ("canonical", canonical), ("reimported", reimported)):
        if not isinstance(value, Mapping):
            raise TypeError(f"{name} must be a Mapping, got {type(value)!r}")

    resolved: dict[str, Any] = {}
    conflicts: list[FieldConflict] = []
    applied: list[str] = []

    for field_name in reimported:
        orig = original.get(field_name)
        canon = canonical.get(field_name)
        reimp = reimported.get(field_name)
        user_changed = reimp != orig
        canonical_changed = canon != orig

        if not user_changed:
            # Rule 1 — the user left it alone, so canonical's own newer value wins.
            resolved[field_name] = canon
        elif not canonical_changed:
            # Rule 2 — only the user changed it; apply cleanly.
            resolved[field_name] = reimp
            applied.append(field_name)
        elif reimp == canon:
            # Both changed, to the same value. Not a conflict: there is nothing for a human
            # to decide, and treating agreement as a conflict would flood the review queue
            # with decisions that have only one possible answer.
            resolved[field_name] = canon
        else:
            # Rule 3 — a genuine conflict. Canonical stays authoritative until a human says
            # otherwise, and the conflict is recorded rather than resolved.
            resolved[field_name] = canon
            conflicts.append(
                FieldConflict(
                    field=field_name,
                    original_value=orig,
                    canonical_value=canon,
                    reimported_value=reimp,
                    receipt_id=receipt_id,
                )
            )

    return ResolutionOutcome(
        resolved=FrozenDict(resolved),
        conflicts=tuple(conflicts),
        applied_fields=tuple(applied),
    )


__all__ = ["three_way_resolve"]

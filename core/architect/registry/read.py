"""The read registry — what definitions exist (`v3-deepdive-26-architect-api.md` §1).

This is the "live, queryable definitions every other API consumes instead of hardcoding
its own" surface (`v3-plan-01-core-apis.md` #25): flag types for Review/Flagging,
reference-identifier types for Persistence, the category taxonomy for Matching and
Inference, tier profiles for Billing, the menu-data schema for Interface.

**It holds definitions, never instance data.** A vendor's real TIN lives in
temporal_learning's entities, a specific flag on a specific receipt lives in
Review/Flagging, a user's tier assignment lives in Billing. If something being added here
has a user or a receipt attached to it, it is in the wrong place.

**On async**: the deep-dive §6 classifies registry reads as async I/O, and they are —
*at the point they are loaded*. This object is the in-memory resolved cache those loads
populate, and its lookups are plain function calls because pretending an in-memory dict
read is awaitable would buy nothing and cost every caller a coroutine. The loader that
fills it from Persistence when that API exists is the async half.

**On mutability**: `_by_kind` is a genuinely mutable internal registry populated at
startup and extended at runtime, so it is a plain `dict` on purpose — `docs/PRINCIPLES.md`
§2.1.1's `FrozenDict` rule covers module-level *constants*, and the distinction is intent,
which should stay visible in the type. Every value it holds is a frozen contract, and
every collection it hands out is a tuple, so nothing a caller receives can be mutated.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from ..contracts import (
    ArchitectError,
    DefinitionKind,
    DefinitionResult,
    RegistryDefinition,
    TaxonomyResult,
    TaxonomyType,
)
from ..errors import ErrorCode, message_for
from .seed_definitions import ALL_SEED_DEFINITIONS

#: Compiled patterns, keyed by the pattern string itself so two identifier types sharing a
#: pattern share one compiled object. Genuinely mutable (a memo table filled on demand),
#: therefore a plain dict, per the module docstring's own distinction.
_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _compiled(pattern: str) -> re.Pattern[str]:
    cached = _PATTERN_CACHE.get(pattern)
    if cached is None:
        cached = re.compile(pattern)
        _PATTERN_CACHE[pattern] = cached
    return cached


def _error(code: str, detail: str = "") -> ArchitectError:
    return ArchitectError(code=code, detail=detail or message_for(code))


class DefinitionRegistry:
    """The queryable set of registered definitions.

    Constructed with the seed set by default. `seed=False` gives a genuinely empty
    registry, which is what a test wanting to assert on exactly its own definitions
    should use rather than working around the seeds.
    """

    def __init__(self, seed: bool = True) -> None:
        self._by_kind: dict[DefinitionKind, dict[str, RegistryDefinition]] = {
            kind: {} for kind in DefinitionKind
        }
        if seed:
            self.register_many(ALL_SEED_DEFINITIONS)

    # ---------------------------------------------------------------- registration

    def register(self, definition: RegistryDefinition) -> DefinitionResult:
        """Register one definition. Errors are returned, never raised (§4.1)."""
        problem = self._validate(definition)
        if problem is not None:
            return DefinitionResult(error=problem)
        self._by_kind[definition.kind][definition.code] = definition
        return DefinitionResult(definition=definition)

    def register_many(self, definitions: Iterable[RegistryDefinition]) -> tuple[ArchitectError, ...]:
        """Register a batch, returning every error rather than stopping at the first.

        A partially-valid batch registers what it can: one bad entry in a consumer's
        startup set should not silently cost that consumer every other definition it
        declared (`docs/PRINCIPLES.md` §4.4).
        """
        errors: list[ArchitectError] = []
        for definition in definitions:
            result = self.register(definition)
            if result.error is not None:
                errors.append(result.error)
        return tuple(errors)

    def deprecate(self, kind: DefinitionKind, code: str) -> DefinitionResult:
        """Mark a definition deprecated. Deliberately not a delete.

        Instance data written against a definition outlives the decision to stop using it,
        so a definition has to stay resolvable long after it stops being offered.
        """
        existing = self._by_kind[kind].get(code)
        if existing is None:
            return DefinitionResult(error=_error(ErrorCode.UNKNOWN_DEFINITION, f"{kind.value}:{code}"))
        from dataclasses import replace

        updated = replace(existing, deprecated=True)
        self._by_kind[kind][code] = updated
        return DefinitionResult(definition=updated)

    def _validate(self, definition: RegistryDefinition) -> ArchitectError | None:
        if not definition.code or not definition.code.strip():
            return _error(ErrorCode.INVALID_DEFINITION, "definition code is empty")
        if definition.kind not in self._by_kind:
            return _error(ErrorCode.UNKNOWN_KIND, str(definition.kind))
        if definition.code in self._by_kind[definition.kind]:
            return _error(
                ErrorCode.DUPLICATE_DEFINITION,
                f"{definition.kind.value}:{definition.code} is already registered",
            )
        # `attributes` is a FrozenDict on the contract; anything Mapping-shaped is
        # acceptable here. The check is against `Mapping`, never `dict` — the 3.15
        # builtin frozendict is not a dict subclass and this branch would silently
        # reject every correctly-typed definition if it were (`docs/PRINCIPLES.md` §2.1).
        if not isinstance(definition.attributes, Mapping):
            return _error(ErrorCode.INVALID_DEFINITION, "attributes must be a mapping")
        if isinstance(definition, TaxonomyType) and definition.parent_code is not None:
            if definition.parent_code not in self._by_kind[DefinitionKind.TAXONOMY_CATEGORY]:
                return _error(ErrorCode.INVALID_PARENT, definition.parent_code)
        return None

    # ---------------------------------------------------------------------- reads

    def get(self, kind: DefinitionKind, code: str) -> DefinitionResult:
        found = self._by_kind[kind].get(code)
        if found is None:
            return DefinitionResult(error=_error(ErrorCode.UNKNOWN_DEFINITION, f"{kind.value}:{code}"))
        return DefinitionResult(definition=found)

    def list(self, kind: DefinitionKind, include_deprecated: bool = False) -> TaxonomyResult:
        """Every definition of one kind, code-sorted for a stable wire order."""
        values = self._by_kind[kind].values()
        chosen = tuple(
            sorted(
                (d for d in values if include_deprecated or not d.deprecated),
                key=lambda d: d.code,
            )
        )
        return TaxonomyResult(definitions=chosen)

    def children(self, parent_code: str) -> TaxonomyResult:
        """Direct children of a taxonomy node. An unknown parent is an error, not empty —
        empty and wrong are genuinely different answers and a caller cannot tell them
        apart otherwise."""
        categories = self._by_kind[DefinitionKind.TAXONOMY_CATEGORY]
        if parent_code not in categories:
            return TaxonomyResult(error=_error(ErrorCode.UNKNOWN_DEFINITION, parent_code))
        found = tuple(
            sorted(
                (d for d in categories.values()
                 if isinstance(d, TaxonomyType) and d.parent_code == parent_code),
                key=lambda d: d.code,
            )
        )
        return TaxonomyResult(definitions=found)

    def ancestors(self, code: str) -> TaxonomyResult:
        """Nearest-first chain up to the root.

        Cycle-guarded: `register` rejects an unknown parent, which makes a cycle
        impossible to build through the public surface, but a store loaded from disk by a
        future Persistence-backed loader has no such guarantee and an unbounded walk
        would hang the caller rather than fail it.
        """
        categories = self._by_kind[DefinitionKind.TAXONOMY_CATEGORY]
        current = categories.get(code)
        if current is None:
            return TaxonomyResult(error=_error(ErrorCode.UNKNOWN_DEFINITION, code))
        chain: list[RegistryDefinition] = []
        seen = {code}
        while isinstance(current, TaxonomyType) and current.parent_code is not None:
            if current.parent_code in seen:
                return TaxonomyResult(
                    definitions=tuple(chain),
                    error=_error(ErrorCode.INVALID_PARENT, f"cycle at {current.parent_code}"),
                )
            seen.add(current.parent_code)
            parent = categories.get(current.parent_code)
            if parent is None:
                return TaxonomyResult(
                    definitions=tuple(chain),
                    error=_error(ErrorCode.INVALID_PARENT, current.parent_code),
                )
            chain.append(parent)
            current = parent
        return TaxonomyResult(definitions=tuple(chain))

    def is_descendant_of(self, code: str, ancestor_code: str) -> bool:
        """Whether `code` sits anywhere under `ancestor_code`. False on any unknown code."""
        result = self.ancestors(code)
        return any(d.code == ancestor_code for d in result.definitions)

    # ----------------------------------------------------------------- validation

    def validate_identifier(self, type_code: str, value: str) -> DefinitionResult:
        """Structural validation of a reference-identifier value against its type.

        Structural only, by design: this catches OCR misreads and malformed entry and says
        nothing about whether the identifier is genuine. A type with no pattern accepts
        any non-empty value rather than rejecting everything.
        """
        found = self._by_kind[DefinitionKind.REFERENCE_IDENTIFIER_TYPE].get(type_code)
        if found is None:
            return DefinitionResult(error=_error(ErrorCode.UNKNOWN_DEFINITION, type_code))
        pattern = getattr(found, "value_pattern", "")
        if not value:
            return DefinitionResult(error=_error(ErrorCode.INVALID_DEFINITION, "empty value"))
        if pattern and not _compiled(pattern).match(value):
            return DefinitionResult(
                error=_error(ErrorCode.INVALID_DEFINITION,
                             f"{value!r} does not match the structure of {type_code}")
            )
        return DefinitionResult(definition=found)

    def knows(self, kind: DefinitionKind, code: str) -> bool:
        """Cheap membership test for a caller that only needs a boolean."""
        return code in self._by_kind[kind]


__all__ = ["DefinitionRegistry"]

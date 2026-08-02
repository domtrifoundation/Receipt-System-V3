"""Vendor alias list and name normalization (`v3-deepdive-26-architect-api.md` §3).

Architect owns the alias *list*. Matching owns the fuzzy scoring that decides which alias
a piece of OCR text is closest to (deep-dive §1: "Matching does the actual fuzzy-matching")
— nothing here scores, ranks, or approximates. Resolution is exact-on-normalized, which is
a genuinely different operation from fuzzy matching and belongs on this side of the line:
it answers "is this string a known spelling of a known corporation", not "which known
corporation is this string most like".

**Normalization is centralized here for a specific reason.** The moment two call sites
each strip punctuation their own way, they disagree about whether two names are the same,
and the disagreement shows up as a duplicate vendor nobody can explain. Every consumer
that needs a comparable form of a vendor name calls `normalize_vendor_name`.

**An alias colliding across two corporations is a genuine conflict and is surfaced, never
silently overwritten** (`docs/PRINCIPLES.md` §4.3) — the losing corporation would
otherwise become quietly unreachable by one of its own names.
"""

from __future__ import annotations

import re
import unicodedata

from common.frozen_dict import FrozenDict

from ..contracts import AliasResult, ArchitectError, VendorAlias
from ..errors import ErrorCode, message_for

#: Trailing corporate-form and jurisdiction words that carry no distinguishing signal on a
#: PH receipt. Stripped only from the *end* of a name: "Philippine Airlines" must keep its
#: first word, while "Jollibee Foods Corporation" and "Jollibee Foods Corp." must collapse
#: to the same normalized form. `FrozenDict` because it is a module-level constant read
#: concurrently and never written (`docs/PRINCIPLES.md` §2.1.1); the values record why each
#: entry is here rather than leaving a bare word list to be second-guessed later.
CORPORATE_SUFFIXES = FrozenDict(
    {
        "inc": "incorporated",
        "incorporated": "incorporated",
        "corp": "corporation",
        "corporation": "corporation",
        "co": "company",
        "company": "company",
        "ltd": "limited",
        "limited": "limited",
        "llc": "limited liability company",
        "ph": "philippines",
        "phil": "philippines",
        "phils": "philippines",
        "philippines": "philippines",
    }
)

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_vendor_name(name: str) -> str:
    """The one canonical normalization: fold case, drop accents and punctuation, collapse
    whitespace, then strip trailing corporate-form words.

    Suffix stripping is iterative because real names stack them ("... Foods Corporation
    Philippines"), and it never strips the last remaining word — a corporation genuinely
    named "Company" would otherwise normalize to the empty string and match everything.
    """
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = _PUNCTUATION.sub(" ", folded.casefold())
    words = [w for w in _WHITESPACE.split(folded) if w]
    while len(words) > 1 and words[-1] in CORPORATE_SUFFIXES:
        words.pop()
    return " ".join(words)


def _error(code: str, detail: str = "") -> ArchitectError:
    return ArchitectError(code=code, detail=detail or message_for(code))


class AliasIndex:
    """The alias list, indexed by normalized form.

    Both maps are genuinely mutable internal registries and therefore plain dicts, per
    `docs/PRINCIPLES.md` §2.1.1's own distinction — every value handed back out is a
    frozen contract or a tuple.
    """

    def __init__(self) -> None:
        self._by_normalized: dict[str, VendorAlias] = {}
        self._by_corporation: dict[str, list[VendorAlias]] = {}

    def add(self, alias: str, corporation_id: str, source: str = "learned") -> AliasResult:
        """Register an alias.

        Re-registering the same alias for the same corporation is idempotent and returns
        the existing entry. Registering it for a *different* corporation is a real
        conflict: it is refused and surfaced rather than resolved by last-write-wins,
        because whichever corporation lost would silently stop being findable under a name
        it is genuinely known by (`docs/PRINCIPLES.md` §4.3).
        """
        normalized = normalize_vendor_name(alias)
        if not normalized:
            return AliasResult(error=_error(ErrorCode.INVALID_DEFINITION, "alias is empty"))
        existing = self._by_normalized.get(normalized)
        if existing is not None:
            if existing.corporation_id == corporation_id:
                return AliasResult(alias=existing)
            return AliasResult(
                error=_error(
                    ErrorCode.DUPLICATE_DEFINITION,
                    f"{alias!r} already resolves to {existing.corporation_id}; "
                    f"refusing to silently repoint it at {corporation_id}",
                )
            )
        record = VendorAlias(
            alias=alias, normalized=normalized, corporation_id=corporation_id, source=source
        )
        self._by_normalized[normalized] = record
        self._by_corporation.setdefault(corporation_id, []).append(record)
        return AliasResult(alias=record)

    def resolve(self, text: str) -> AliasResult:
        """Exact-on-normalized resolution. No scoring, no nearest match, no threshold."""
        normalized = normalize_vendor_name(text)
        found = self._by_normalized.get(normalized)
        if found is None:
            return AliasResult(error=_error(ErrorCode.UNKNOWN_CORPORATION, text))
        return AliasResult(alias=found)

    def aliases_for(self, corporation_id: str) -> tuple[VendorAlias, ...]:
        return tuple(self._by_corporation.get(corporation_id, ()))

    def surface_forms(self, corporation_id: str) -> tuple[str, ...]:
        """The alias strings as originally written, for display and export."""
        return tuple(a.alias for a in self._by_corporation.get(corporation_id, ()))

    def repoint(self, alias: str, corporation_id: str, source: str = "curation") -> AliasResult:
        """Deliberately move an alias to a different corporation.

        The explicit, auditable counterpart to `add`'s refusal: a near-duplicate merge
        approved through the moderation pipeline genuinely needs to repoint aliases, and it
        should have to say so rather than getting there by re-adding and hoping.
        """
        normalized = normalize_vendor_name(alias)
        if not normalized:
            return AliasResult(error=_error(ErrorCode.INVALID_DEFINITION, "alias is empty"))
        existing = self._by_normalized.get(normalized)
        if existing is not None:
            bucket = self._by_corporation.get(existing.corporation_id, [])
            self._by_corporation[existing.corporation_id] = [
                a for a in bucket if a.normalized != normalized
            ]
        record = VendorAlias(
            alias=alias, normalized=normalized, corporation_id=corporation_id, source=source
        )
        self._by_normalized[normalized] = record
        self._by_corporation.setdefault(corporation_id, []).append(record)
        return AliasResult(alias=record)

    def __len__(self) -> int:
        return len(self._by_normalized)


__all__ = ["CORPORATE_SUFFIXES", "AliasIndex", "normalize_vendor_name"]

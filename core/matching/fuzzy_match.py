"""Forward matching — `rapidfuzz`-backed candidate scoring (`v3-deepdive-15-matching-api.md`
§3, §9).

`rapidfuzz` is a C/Cython extension already GIL-released during the actual comparison
(deep-dive §6), so plain threading already achieves real parallelism for a bulk matching sweep
without multiprocessing or free-threading considerations. `fuzz.WRatio` is the confirmed
default scorer (§3) — a weighted combination of several ratio functions that handles
partial/reordered-token matches better than plain Levenshtein alone, reasoned rather than
bench-measured (§8's own "scorer bench comparison" testing hook, covered in
`tests/unit/core/matching/test_fuzzy_match.py`).

**§9's four V2-hard-learned pitfalls are real design requirements here, not a risk list**:

1. *Case sensitivity* — `normalize_for_scoring` casefolds both sides before any scoring call.
2. *Over-eager collapsing of distinct short names* — `_passes_short_name_floor` refuses to
   score two strings as a match once either side (after generic-term stripping) is shorter
   than `SHORT_NAME_FLOOR`, unless they are exactly equal. Short strings collapse too easily
   under naive ratio scoring; a floor on length is cheaper and more legible than tuning the
   scorer's own threshold down to compensate.
3. *Generic words causing false positives* — `GENERIC_TERMS` is stripped from both sides
   before scoring, so two unrelated vendors that both happen to contain "Store" do not score
   artificially high on that shared, undistinguishing word alone.
4. *Needing multiple sightings before trusting a correction* — this is deliberately **not**
   implemented here. It is Architect's `temporal_learning` confidence-accumulation model
   (its own deep-dive §5): a single low-confidence local observation never overriding an
   existing higher-confidence global fact is a *learning* decision, not a *scoring* one, and
   reimplementing it in this module would be exactly the kind of parallel taxonomy/logic
   `docs/PRINCIPLES.md` §3.4 exists to prevent.

**This is deliberately not the same normalization as Architect's exact-alias resolution**
(`core/architect/vendor_directory/aliases.normalize_vendor_name`), which aggressively strips
trailing corporate-form words for exact-match lookup. Fuzzy scoring needs comparably-cased,
comparably-spaced text to score against — not text that has already had distinguishing tokens
stripped off the end, which is a different operation solving a different problem (deep-dive
§1: "Architect owns the alias list; Matching owns the fuzzy scoring").
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Callable

from rapidfuzz import fuzz

from common.frozen_dict import FrozenDict

from .contracts import DEFAULT_FORWARD_LIMIT, MatchCandidate, MatchSource, VendorCandidate
from .metrics import MatchMetricsCollector

#: Category-generic words stripped from both sides before scoring (§9, pitfall 3). Values
#: record *why* each entry is here, the same documentation discipline Architect's own
#: `CORPORATE_SUFFIXES` table uses — a bare word list invites being second-guessed later.
#: `FrozenDict` because this is a module-level constant read concurrently and never written
#: (`docs/PRINCIPLES.md` §2.1.1).
GENERIC_TERMS: FrozenDict = FrozenDict(
    {
        "store": "generic retail-outlet word",
        "shop": "generic retail-outlet word",
        "mart": "generic retail-outlet word",
        "grocery": "generic retail-outlet word",
        "market": "generic retail-outlet word",
        "restaurant": "generic food-service word",
        "eatery": "generic food-service word",
        "cafe": "generic food-service word",
        "diner": "generic food-service word",
        "food": "generic food-service word",
        "foods": "generic food-service word",
        "center": "generic venue word",
        "centre": "generic venue word (UK/PH spelling)",
        "corp": "corporate-form word, not a distinguishing name token",
        "corporation": "corporate-form word, not a distinguishing name token",
        "inc": "corporate-form word, not a distinguishing name token",
        "co": "corporate-form word, not a distinguishing name token",
    }
)

#: Below this length (in normalized, generic-stripped characters), two strings only ever
#: score as a match when they are exactly equal (§9, pitfall 2).
SHORT_NAME_FLOOR: int = 4

Scorer = Callable[[str, str], float]


def normalize_for_scoring(text: str) -> str:
    """Casefold and collapse whitespace only. See the module docstring for why this is not
    Architect's own alias-resolution normalization."""
    return " ".join((text or "").split()).casefold()


def _strip_generic_terms(normalized: str) -> str:
    """Drop `GENERIC_TERMS` tokens, but never down to nothing.

    A vendor genuinely named "Store" (or one whose *only* remaining word after OCR noise is
    a generic term) would otherwise normalize to the empty string and stop being comparable
    at all — the same "never strip the last remaining word" guard Architect's own
    `normalize_vendor_name` applies to corporate suffixes, applied here to generic terms.
    """
    words = [w for w in normalized.split() if w not in GENERIC_TERMS]
    stripped = " ".join(words)
    return stripped if stripped else normalized


def _passes_short_name_floor(a: str, b: str) -> bool:
    if min(len(a), len(b)) >= SHORT_NAME_FLOOR:
        return True
    return a == b


def score_pair(query: str, candidate: str, *, scorer: Scorer = fuzz.WRatio) -> float:
    """Score one query string against one candidate string, all four §9 safeguards applied.

    Returns `0.0` for anything that normalizes to nothing on either side, or that fails the
    short-name floor — a real, meaningful zero, not a sentinel a caller has to special-case.
    """
    normalized_query = normalize_for_scoring(query)
    normalized_candidate = normalize_for_scoring(candidate)
    if not normalized_query or not normalized_candidate:
        return 0.0
    scoring_query = _strip_generic_terms(normalized_query)
    scoring_candidate = _strip_generic_terms(normalized_candidate)
    if not _passes_short_name_floor(scoring_query, scoring_candidate):
        return 0.0
    return float(scorer(scoring_query, scoring_candidate))


def best_name_match(
    query: str, candidate: VendorCandidate, *, scorer: Scorer = fuzz.WRatio
) -> tuple[float, str]:
    """Score `query` against a candidate's canonical name and every alias, returning the
    best `(score, matched_name)` pair.

    `matched_name` is the alias itself when an alias scored highest, distinct from the
    canonical name — deep-dive §1: "Architect owns the alias list; Matching owns the fuzzy
    scoring that decides which alias a piece of OCR text is closest to." A caller can tell
    which surface form actually won rather than only ever seeing the canonical name.
    """
    best_score = 0.0
    best_name = candidate.name
    for name in (candidate.name, *candidate.aliases):
        score = score_pair(query, name, scorer=scorer)
        if score > best_score:
            best_score = score
            best_name = name
    return best_score, best_name


def match_forward(
    extracted: str,
    candidates: Sequence[VendorCandidate],
    limit: int = DEFAULT_FORWARD_LIMIT,
    *,
    scorer: Scorer = fuzz.WRatio,
    metrics: MatchMetricsCollector | None = None,
) -> list[MatchCandidate]:
    """The forward candidate lookup (§3): every candidate scored against `extracted`, ranked
    highest score first, ties broken by canonical name so two equally-strong answers resolve
    the same way on every call.

    Zero-scoring candidates are dropped rather than returned at the bottom of the list — a
    caller asking "what matched" should not have to filter out `score == 0.0` entries itself.
    """
    if metrics is not None:
        metrics.increment("forward_match_calls")
    scored: list[MatchCandidate] = []
    for candidate in candidates:
        score, matched_name = best_name_match(extracted, candidate, scorer=scorer)
        if metrics is not None:
            metrics.increment("candidates_scored")
        if score <= 0:
            continue
        scored.append(
            MatchCandidate(
                canonical_name=candidate.name,
                score=score,
                source=MatchSource.FORWARD,
                entity_id=candidate.entity_id,
                entity_kind=candidate.entity_kind,
                tin=candidate.tin,
                category_code=candidate.category_code,
                matched_alias=matched_name if matched_name != candidate.name else "",
                raw=FrozenDict({"scorer": scorer.__name__ if hasattr(scorer, "__name__") else "custom"}),
            )
        )
    scored.sort(key=lambda c: (-c.score, c.canonical_name))
    return scored[: max(limit, 0)]


__all__ = [
    "GENERIC_TERMS",
    "SHORT_NAME_FLOOR",
    "best_name_match",
    "match_forward",
    "normalize_for_scoring",
    "score_pair",
]

"""The two-way match's reverse direction (`v3-deepdive-15-matching-api.md` §4).

Not just "does this extracted string match a known vendor" (forward, `fuzzy_match.py`), but
also "does any *known* vendor name or alias appear anywhere in the full raw OCR text" —
catching a receipt where the primary field-extraction missed or mangled the vendor line, but
the vendor's own name is still legible somewhere else on the receipt.

**This is explicitly a cost-bounding requirement, not an unconstrained scan** (§4): the known-
vendor universe (via Architect's Wikidata-seeded directory) could be large, and scanning every
candidate name against every character of every receipt's raw text without bounding scope would
be a real, avoidable performance problem. `plausibility_window` slices `raw_ocr_text` down to
its own leading window — "the first N characters, where a receipt's vendor line typically
lives" — *before* any scoring happens, so cost scales with the window, never with however long
the raw OCR text actually is. `test_reverse_gazetteer.py`'s own cost-bounding tests are the
concrete guard for this: a vendor mention placed beyond the window must never be found, and the
scan must stay fast as the candidate universe grows.

The exact scoping heuristic (a leading-character window) is a reasoned placeholder, not an
assumed-optimal one — deep-dive §9's own first open question, worth bench-tuning against real
receipt layouts, shipped as its stated default rather than left unresolved.
"""

from __future__ import annotations

from collections.abc import Sequence

from rapidfuzz import fuzz

from common.frozen_dict import FrozenDict

from .contracts import (
    DEFAULT_FORWARD_LIMIT,
    DEFAULT_PLAUSIBILITY_WINDOW,
    MatchCandidate,
    MatchSource,
    VendorCandidate,
)
from .fuzzy_match import score_pair
from .metrics import MatchMetricsCollector


def reverse_gazetteer_scan(
    raw_ocr_text: str,
    candidates: Sequence[VendorCandidate],
    plausibility_window: int = DEFAULT_PLAUSIBILITY_WINDOW,
    limit: int = DEFAULT_FORWARD_LIMIT,
    *,
    metrics: MatchMetricsCollector | None = None,
) -> list[MatchCandidate]:
    """Scan known vendor names/aliases against `raw_ocr_text`'s own leading plausibility
    window, ranked highest score first.

    Uses `rapidfuzz.fuzz.partial_ratio` rather than `fuzz.WRatio`: this is a "does this name
    appear as a substring-like match somewhere in a larger block of text" question, a
    genuinely different comparison from the forward pass's "are these two whole strings the
    same name" — using the same whole-string scorer here would under-score a short, correctly-
    spelled vendor name sitting inside a long noisy OCR block purely because of the length
    mismatch, not because of any real dissimilarity.

    §9's case-sensitivity, generic-term and short-name-floor safeguards all still apply here
    via the shared `fuzzy_match.score_pair` — this module owns *where to look*, not a second
    opinion about *how similar two strings are*.
    """
    if metrics is not None:
        metrics.increment("reverse_scan_calls")
    window = raw_ocr_text[: max(plausibility_window, 0)] if raw_ocr_text else ""
    if not window.strip():
        return []

    lowered_window = window.casefold()
    scored: list[MatchCandidate] = []
    for candidate in candidates:
        best_score = 0.0
        best_name = candidate.name
        best_literal = False
        for name in (candidate.name, *candidate.aliases):
            score = score_pair(name, window, scorer=fuzz.partial_ratio)
            if metrics is not None:
                metrics.increment("candidates_scored")
            # `partial_ratio` saturates at 100 for any name whose best-aligning substring
            # matches, so a canonical name and one of its own aliases routinely tie at the top
            # — "Jollibee Foods Corporation" and "Jollibee" both score 100 against text
            # containing only the latter. The score alone therefore cannot say *which* name
            # the receipt actually carried, and reporting the canonical one purely because it
            # was compared first would tell a human reviewing the match something untrue.
            #
            # Breaking the tie on a literal appearance is what recovers that: a name that
            # occurs verbatim in the window is the one the OCR text genuinely contains, and
            # `matched_alias` becomes real evidence rather than an artifact of iteration order.
            literal = name.casefold() in lowered_window
            if score > best_score or (score == best_score and literal and not best_literal):
                best_score = score
                best_name = name
                best_literal = literal
        if best_score <= 0:
            continue
        scored.append(
            MatchCandidate(
                canonical_name=candidate.name,
                score=best_score,
                source=MatchSource.REVERSE_GAZETTEER,
                entity_id=candidate.entity_id,
                entity_kind=candidate.entity_kind,
                tin=candidate.tin,
                category_code=candidate.category_code,
                matched_alias=best_name if best_name != candidate.name else "",
                raw=FrozenDict({"scorer": "partial_ratio", "window_chars": str(len(window))}),
            )
        )
    scored.sort(key=lambda c: (-c.score, c.canonical_name))
    return scored[: max(limit, 0)]


__all__ = ["reverse_gazetteer_scan"]

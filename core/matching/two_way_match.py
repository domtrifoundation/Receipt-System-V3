"""The two-way match, combined — forward lookup plus reverse gazetteer scan, merged into one
ranked answer (`v3-deepdive-15-matching-api.md` §3, §4).

`match_vendor` is **the one reusable function** `docs/PRINCIPLES.md` §1.9 asks for, and this
API's own CLAUDE.md names Matching as one of the two concrete cases that principle was
generalised from: Execution Core's synchronous `MATCHED` stage calls it once per new receipt;
Reconciliation's idle-time sweep calls the identical function against an already-written, older
one. Neither caller gets its own copy of the matching logic, so a fixed scorer bug or a better
safeguard benefits both the moment it ships, never just receipts processed from that point
forward — the same guarantee `core/geo_address/corroboration.py`'s own
`geocode_with_corroboration` gives its two callers, and this module is written as a deliberate
sibling of that one.

**Not listed in the deep-dive's own §2 package layout.** That layout names `fuzzy_match.py`
(forward scoring) and `reverse_gazetteer.py` (the reverse direction) as two separate concerns,
but names no module for combining them into one ranked answer — the same gap `geo_address`'s
own `corroboration.py` filled for its API, added with the identical reasoning.
"""

from __future__ import annotations

from .contracts import MatchCandidate, MatchError, MatchRequest, MatchResult
from .errors import InvalidMatchRequest, code_for, summary_for
from .fuzzy_match import match_forward
from .metrics import MatchMetricsCollector
from .reverse_gazetteer import reverse_gazetteer_scan


def match_vendor(request: MatchRequest, *, metrics: MatchMetricsCollector | None = None) -> MatchResult:
    """Resolve `request` against both matching axes, corroborating them into one ranked list.

    Degrades gracefully throughout (`docs/PRINCIPLES.md` §4.4): an empty `candidates` tuple is
    a legitimate "nothing to search against yet" answer, not an error, and a candidate that
    scores zero on both axes is simply absent from the ranked result rather than reported as a
    failure. Only a request with no string to search *with* at all — both `extracted_text` and
    `raw_ocr_text` empty — is genuinely malformed (`errors.InvalidMatchRequest`).

    Forward and reverse results for the same entity are merged by `entity_id` (or canonical
    name, for a candidate with none), keeping whichever axis scored it higher. A genuine tie is
    resolved in favour of the forward result: the forward pass matched the field OCR actually
    extracted as the vendor line, which is a stronger signal than a name merely appearing
    somewhere in the raw text, all else equal (`docs/PRINCIPLES.md` §4.3 — this is a real,
    stated tie-break rule, not a silent, arbitrary pick).
    """
    if metrics is not None:
        metrics.increment("two_way_match_calls")

    if not request.extracted_text.strip() and not request.raw_ocr_text.strip():
        if metrics is not None:
            metrics.increment("malformed_requests")
        exc = InvalidMatchRequest("both extracted_text and raw_ocr_text are empty")
        code = code_for(exc)
        return MatchResult(error=MatchError(code=code, detail=summary_for(code)))

    if not request.candidates:
        if metrics is not None:
            metrics.increment("empty_candidate_sets")
        return MatchResult(candidates=())

    forward: list[MatchCandidate] = []
    if request.extracted_text.strip():
        forward = match_forward(
            request.extracted_text, request.candidates, limit=request.limit, metrics=metrics
        )

    reverse: list[MatchCandidate] = []
    if request.raw_ocr_text.strip():
        reverse = reverse_gazetteer_scan(
            request.raw_ocr_text,
            request.candidates,
            plausibility_window=request.plausibility_window,
            limit=request.limit,
            metrics=metrics,
        )

    merged: dict[str, MatchCandidate] = {}
    for candidate in (*forward, *reverse):
        key = candidate.entity_id or candidate.canonical_name
        existing = merged.get(key)
        # Strictly greater only: forward is processed first, so a reverse candidate must
        # outscore it to win a tie — the stated forward-wins-ties rule above.
        if existing is None or candidate.score > existing.score:
            merged[key] = candidate

    ranked = sorted(merged.values(), key=lambda c: (-c.score, c.canonical_name))
    ranked = ranked[: max(request.limit, 0)]
    if metrics is not None:
        metrics.increment("candidates_returned", len(ranked))
    return MatchResult(candidates=tuple(ranked))


__all__ = ["match_vendor"]

"""Corroboration layer — tiered agreement, deterministic first, no LLM in the hot path
(deep-dive §7.3, resolving file 04's open "LLM vs deterministic vs hybrid" question).

**Why not pure LLM arbitration** (§7.1): every multi-engine call would block on an
Inference API round-trip even when two engines already agree byte-for-byte — real added
latency and inference load for the overwhelming common case that needs no arbitration.

**Why not pure deterministic voting either** (§7.2): OCR engines rarely disagree by
producing two different *clean* readings — they garble different characters in
mostly-similar text. A naive string-equality or even fuzzy-match vote cannot resolve a
genuine three-way split, or tell "dropped a decimal point" from "read a different, more
correct number."

**The algorithm** (§7.3): normalize every valid reading, compute pairwise
`rapidfuzz.fuzz.token_sort_ratio` similarity, then classify:
`UNANIMOUS` (every pair agrees) -> `MAJORITY` (a majority cluster with an outlier) ->
`SPLIT` (no majority, or a reading fails a basic sanity check) -> `SINGLE_SOURCE` (one
valid reading) -> `NONE` (no valid reading at all).

**Per-engine trailing-accuracy weighting is deliberately not implemented here.** The
deep-dive's own §7.3/§9 is explicit that `merged_text` among an agreeing set should prefer
"the highest-historical-accuracy engine," but that score needs real measurement and a real
home (resolved in §9 as Architect API's responsibility, this API only ever a consumer of
it) — inventing a hardcoded engine ranking here to fill that gap would be exactly the kind
of un-measured assumption the deep-dive explicitly warns against. Until that integration
exists, the tie-break among an agreeing/majority set is deterministic and stated as a
placeholder: prefer the reading with the highest `mean_confidence` (a real per-engine
signal, just not a *trailing*, learned one), falling back to the longest normalized text.
"""

from __future__ import annotations

import re

from .contracts import AgreementLevel, EngineReading, OcrResult

__all__ = ["merge_readings", "normalize_text"]

#: `token_sort_ratio` score (0-100 from rapidfuzz, used here as 0.0-1.0) above which two
#: readings are considered "agreeing." Not bench-tuned yet — a reasoned starting point
#: (typo-level divergence between two decent engines rarely drops below this), same
#: "resolved default, refinable from real measurement" posture the Tesseract PSM default
#: takes (deep-dive §9).
AGREEMENT_THRESHOLD = 0.85

#: Fixed confidence floor for a genuine `SPLIT` — deliberately low and honest about the
#: uncertainty rather than manufacturing false confidence (deep-dive §7.3's own framing).
SPLIT_CONFIDENCE_FLOOR = 0.2

#: `SINGLE_SOURCE`'s own confidence when the one valid reading carries no confidence
#: signal at all (Windows OCR, tier-0 text-layer) — a fallback, not a real measurement.
NO_SIGNAL_CONFIDENCE = 0.5

_WHITESPACE_RE = re.compile(r"\s+")
_MIN_SANE_LENGTH = 3


def normalize_text(text: str) -> str:
    """Whitespace collapse plus common OCR-noise character fixes — NOT semantic parsing,
    just text-level cleanup (deep-dive §7.3 step 1)."""
    collapsed = _WHITESPACE_RE.sub(" ", text).strip()
    # A handful of near-universal OCR substitution errors, cheap enough to always apply.
    collapsed = collapsed.replace("|", "I").replace("{}", "()")
    return collapsed


def _is_sane(normalized: str) -> bool:
    return len(normalized) >= _MIN_SANE_LENGTH and any(c.isalnum() for c in normalized)


def _similarity(a: str, b: str) -> float:
    from rapidfuzz import fuzz

    return fuzz.token_sort_ratio(a, b) / 100.0


def _best_of(readings: tuple[EngineReading, ...], normalized_by_reading: dict) -> str:
    """The stated-placeholder tie-break — see module docstring."""
    def sort_key(reading: EngineReading) -> tuple[float, int]:
        confidence = reading.mean_confidence if reading.mean_confidence is not None else 0.0
        return (confidence, len(normalized_by_reading[id(reading)]))

    best = max(readings, key=sort_key)
    return normalized_by_reading[id(best)]


def _connected_components(
    valid: tuple[EngineReading, ...], agrees: dict[tuple[int, int], bool]
) -> list[list[EngineReading]]:
    """Groups readings into clusters where every pair inside a cluster agrees transitively
    through at least one path — a plain union-find over `valid`'s own indices."""
    parent = list(range(len(valid)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for (i, j), agree in agrees.items():
        if agree:
            union(i, j)

    clusters: dict[int, list[EngineReading]] = {}
    for idx, reading in enumerate(valid):
        clusters.setdefault(find(idx), []).append(reading)
    return list(clusters.values())


def merge_readings(readings: tuple[EngineReading, ...]) -> OcrResult:
    valid: list[EngineReading] = []
    normalized_by_reading: dict[int, str] = {}
    for reading in readings:
        if reading.error is not None:
            continue
        normalized = normalize_text(reading.text)
        if not _is_sane(normalized):
            continue
        valid.append(reading)
        normalized_by_reading[id(reading)] = normalized

    if not valid:
        return OcrResult(
            readings=readings, merged_text="", agreement=AgreementLevel.NONE, confidence=0.0
        )

    if len(valid) == 1:
        only = valid[0]
        confidence = only.mean_confidence if only.mean_confidence is not None else NO_SIGNAL_CONFIDENCE
        return OcrResult(
            readings=readings, merged_text=normalized_by_reading[id(only)],
            agreement=AgreementLevel.SINGLE_SOURCE, confidence=confidence,
        )

    agrees: dict[tuple[int, int], bool] = {}
    similarities: list[float] = []
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            score = _similarity(
                normalized_by_reading[id(valid[i])], normalized_by_reading[id(valid[j])]
            )
            similarities.append(score)
            agrees[(i, j)] = score >= AGREEMENT_THRESHOLD

    if all(agrees.values()):
        merged_text = _best_of(tuple(valid), normalized_by_reading)
        confidence = sum(similarities) / len(similarities)
        return OcrResult(
            readings=readings, merged_text=merged_text,
            agreement=AgreementLevel.UNANIMOUS, confidence=confidence,
        )

    clusters = _connected_components(tuple(valid), agrees)
    largest = max(clusters, key=len)
    if len(largest) > len(valid) / 2:
        merged_text = _best_of(tuple(largest), normalized_by_reading)
        in_cluster_scores = [
            _similarity(
                normalized_by_reading[id(largest[i])], normalized_by_reading[id(largest[j])]
            )
            for i in range(len(largest)) for j in range(i + 1, len(largest))
        ]
        base_confidence = (
            sum(in_cluster_scores) / len(in_cluster_scores) if in_cluster_scores else 1.0
        )
        outlier_penalty = 1.0 - (len(valid) - len(largest)) / len(valid)
        confidence = base_confidence * outlier_penalty
        return OcrResult(
            readings=readings, merged_text=merged_text,
            agreement=AgreementLevel.MAJORITY, confidence=confidence,
        )

    merged_text = _best_of(tuple(valid), normalized_by_reading)
    return OcrResult(
        readings=readings, merged_text=merged_text,
        agreement=AgreementLevel.SPLIT, confidence=SPLIT_CONFIDENCE_FLOOR,
    )

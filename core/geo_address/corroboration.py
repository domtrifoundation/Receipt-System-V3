"""Multi-provider + multi-candidate cross-check (`v3-deepdive-16-geo-address-api.md` §3, §5).

`geocode_with_corroboration` is **the one reusable function** `docs/PRINCIPLES.md` §1.9 asks
for: Execution Core's synchronous `GEOD` stage calls it for a new receipt, Reconciliation's
idle-time sweep calls the identical function against an already-written, older one. Neither
gets its own copy, so a better provider or a fixed agreement threshold benefits both callers
the moment it ships, never just receipts processed from that point forward.

**Two independent corroboration axes, not one** (§3): which *providers* to query (a Provider
Registry corroboration set, `docs/PRINCIPLES.md` §1.2) and which *OCR candidate string* each
provider is asked about (several ranked readings, not just the top one — every provider
confidently geocoding a wrong top reading is a real failure mode only the second axis guards
against). Both run concurrently via `asyncio.gather`, never a `for` loop of awaited calls (§5
— this is the literal fix for V2's own `urllib.request.urlopen()` sequential-loop bug).

**A genuine cross-provider disagreement is surfaced, never silently resolved** (`docs/
PRINCIPLES.md` §4.3): `AgreementLevel.SPLIT` leaves `normalized_address` at `None` rather than
guessing, reusing OCR API's own tiered deterministic-then-escalate shape (deep-dive §9,
resolved open question) rather than a second, independently-invented voting scheme.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Sequence

from rapidfuzz import fuzz

from .cache import GeoCache
from .contracts import (
    AGREEMENT_RANK,
    AgreementLevel,
    GeoAddress,
    GeoError,
    GeoQuery,
    GeoResult,
    ProviderCandidateResult,
)
from .errors import InvalidQuery, code_for
from .metrics import GeoMetricsCollector
from .providers.base import GeoProvider
from .reverse_check import reverse_check

#: Pairwise `rapidfuzz.fuzz.token_sort_ratio` (0-100) above which two providers' own formatted
#: addresses are treated as "the same place" — OCR API's own §7.3 similarity gate, applied
#: here to provider output instead of OCR engine output (deep-dive §9's resolved reuse).
AGREEMENT_THRESHOLD = 85.0

#: The confidence a genuine `SPLIT` is reported at. Fixed and low rather than derived from the
#: disagreeing readings themselves — a formula that tried to "average" a real disagreement into
#: a number would be exactly the silent resolution §4.3 forbids, just dressed up as one.
SPLIT_CONFIDENCE = 0.2

_WinningCandidate = tuple[str, AgreementLevel, float, "GeoAddress | None", bool, str]


async def geocode_with_corroboration(
    query: GeoQuery,
    providers: Sequence[GeoProvider],
    *,
    cache: GeoCache | None = None,
    metrics: GeoMetricsCollector | None = None,
) -> GeoResult:
    """Resolve `query` against `providers`, corroborating both axes described above.

    Degrades gracefully throughout (`docs/PRINCIPLES.md` §4.4): a provider with no working
    transport is skipped, a provider whose call fails is recorded in `degraded_providers`, and
    every provider being unavailable this run falls back to the last cached answer rather than
    returning nothing, honestly marked `cache_stale=True`. Only a malformed request — no usable
    candidate strings, or a `providers` filter matching nothing registered — is a real `error`.
    """
    if metrics is not None:
        metrics.increment("geocode_calls")

    candidates = tuple(c.strip() for c in query.candidate_strings if c and c.strip())
    if not candidates:
        exc = InvalidQuery("no candidate strings supplied")
        return GeoResult(error=GeoError(code=code_for(exc), detail=str(exc)))

    requested = {name.strip().lower() for name in query.providers if name.strip()}
    selected = tuple(p for p in providers if not requested or p.name.lower() in requested)
    if not selected:
        exc = InvalidQuery("no registered provider matches the requested provider set")
        return GeoResult(error=GeoError(code=code_for(exc), detail=str(exc)))

    cache_key = ""
    cached_stale: GeoResult | None = None
    if cache is not None:
        cache_key = cache.normalize(candidates, query.country_code, tuple(p.name for p in selected))
        hit = cache.get(cache_key)
        if hit is not None:
            result, stale = hit
            if not stale:
                if metrics is not None:
                    metrics.increment("cache_hits")
                return _replace(result, from_cache=True, cache_stale=False)
            cached_stale = result
            if metrics is not None:
                metrics.increment("cache_stale_hits")
        elif metrics is not None:
            metrics.increment("cache_misses")

    available = tuple(p for p in selected if p.is_available())
    unavailable_names = tuple(sorted(p.name for p in selected if p not in available))
    if metrics is not None:
        metrics.increment("provider_unavailable", len(unavailable_names))

    by_candidate, failed_names = await _forward_matrix(candidates, available, query.country_code)
    if metrics is not None:
        metrics.increment("provider_calls", len(candidates) * len(available))
        metrics.increment("provider_failures", len(failed_names))

    degraded = tuple(sorted(set(unavailable_names) | failed_names))
    winner = _pick_winning_candidate(candidates, by_candidate)

    if winner is None:
        if metrics is not None:
            metrics.increment("all_providers_down")
        if cached_stale is not None:
            return _replace(
                cached_stale,
                from_cache=True,
                cache_stale=True,
                degraded_providers=tuple(
                    sorted(set(cached_stale.degraded_providers) | set(degraded))
                ),
            )
        return GeoResult(degraded_providers=degraded)

    candidate_string, level, confidence, address, conflict, conflict_detail = winner
    provider_results = tuple(by_candidate[candidate_string])

    vendor_name_at_address = ""
    discrepancy = False
    reverse_results: tuple[ProviderCandidateResult, ...] = ()
    if address is not None and query.vendor_name_hint.strip():
        vendor_name_at_address, discrepancy, reverse_results = await reverse_check(
            address, query.vendor_name_hint, available
        )
        if discrepancy and metrics is not None:
            metrics.increment("vendor_discrepancies_detected")

    if conflict and metrics is not None:
        metrics.increment("conflicts_detected")

    final = GeoResult(
        normalized_address=address,
        confidence=confidence,
        agreement=level,
        matched_candidate_string=candidate_string,
        provider_results=provider_results + reverse_results,
        vendor_name_at_address=vendor_name_at_address,
        vendor_name_discrepancy=discrepancy,
        conflict=conflict,
        conflict_detail=conflict_detail,
        degraded_providers=degraded,
    )

    if cache is not None and level is not AgreementLevel.NONE:
        cache.put(cache_key, final)

    return final


# ------------------------------------------------------------------- forward matrix


async def _forward_matrix(
    candidates: tuple[str, ...], providers: tuple[GeoProvider, ...], country_code: str
) -> tuple[dict[str, list[ProviderCandidateResult]], set[str]]:
    """Every `(provider, candidate)` pair, run concurrently (§5) — never a sequential loop.

    Returns the results grouped by candidate string, plus the set of provider names for whom
    *every* attempted call failed. A provider that never ran at all because it was already
    unavailable is not in that set — the caller already excluded it from `providers`.
    """
    if not providers:
        return {c: [] for c in candidates}, set()

    pairs = [(candidate, provider) for candidate in candidates for provider in providers]
    gathered = await asyncio.gather(
        *(_call_geocode(provider, candidate, country_code) for candidate, provider in pairs),
        return_exceptions=True,
    )

    by_candidate: dict[str, list[ProviderCandidateResult]] = {c: [] for c in candidates}
    attempts: dict[str, int] = {p.name: 0 for p in providers}
    failures: dict[str, int] = {p.name: 0 for p in providers}
    for (candidate, provider), outcome in zip(pairs, gathered, strict=True):
        attempts[provider.name] += 1
        if isinstance(outcome, BaseException):
            failures[provider.name] += 1
            continue
        by_candidate[candidate].append(outcome)
        if not outcome.ok:
            failures[provider.name] += 1
    failed_names = {name for name, count in failures.items() if count and count == attempts[name]}
    return by_candidate, failed_names


async def _call_geocode(
    provider: GeoProvider, candidate: str, country_code: str
) -> ProviderCandidateResult:
    """One provider call, converted to data on failure (`docs/PRINCIPLES.md` §4.1, §4.4).

    A provider adapter raises on failure by contract (`providers/base.py`); this is the one
    place that exception becomes a `ProviderCandidateResult.error` instead of propagating, so
    `asyncio.gather` above never has to special-case a provider's own failure mode.
    """
    try:
        return await provider.geocode(candidate, country_code=country_code)
    except Exception as exc:  # noqa: BLE001 - a provider's own failure must never fail the run
        return ProviderCandidateResult(
            provider=provider.name,
            candidate_string=candidate,
            error=GeoError(code=code_for(exc), detail=str(exc)),
        )


# ------------------------------------------------------------------- agreement


def _pick_winning_candidate(
    candidates: tuple[str, ...], by_candidate: dict[str, list[ProviderCandidateResult]]
) -> _WinningCandidate | None:
    """The second corroboration axis (§3): score every candidate string's own cross-provider
    agreement and report whichever scores best — not simply OCR's own top-ranked reading.

    Ranking is `AGREEMENT_RANK` first (unanimous beats majority beats single-source beats
    split beats none), then confidence, then the candidate's own OCR rank as the final
    tie-break — so two equally-strong answers prefer the reading OCR itself trusted more.
    """
    best: _WinningCandidate | None = None
    best_key: tuple[int, float, int] | None = None
    for rank, candidate in enumerate(candidates):
        level, confidence, address, conflict, detail = _agreement_for_group(by_candidate[candidate])
        if level is AgreementLevel.NONE:
            continue
        key = (AGREEMENT_RANK[level], confidence, -rank)
        if best_key is None or key > best_key:
            best_key = key
            best = (candidate, level, confidence, address, conflict, detail)
    return best


def _agreement_for_group(
    results: list[ProviderCandidateResult],
) -> tuple[AgreementLevel, float, "GeoAddress | None", bool, str]:
    """OCR API's own tiered shape (`v3-deepdive-01-ocr-api.md` §7.3), applied to provider
    output instead of OCR engine output (deep-dive §9's resolved reuse)."""
    successes = [r for r in results if r.ok and r.address is not None]
    if not successes:
        return AgreementLevel.NONE, 0.0, None, False, ""
    if len(successes) == 1:
        only = successes[0]
        return AgreementLevel.SINGLE_SOURCE, only.confidence, only.address, False, ""

    pairwise: dict[tuple[int, int], float] = {}
    for i in range(len(successes)):
        for j in range(i + 1, len(successes)):
            pairwise[(i, j)] = fuzz.token_sort_ratio(
                successes[i].address.formatted, successes[j].address.formatted
            )

    agrees_with = [
        sum(
            1
            for (i, j), score in pairwise.items()
            if (i == idx or j == idx) and score >= AGREEMENT_THRESHOLD
        )
        for idx in range(len(successes))
    ]

    if all(score >= AGREEMENT_THRESHOLD for score in pairwise.values()):
        best = max(successes, key=lambda r: r.confidence)
        mean_similarity = sum(pairwise.values()) / len(pairwise)
        return AgreementLevel.UNANIMOUS, mean_similarity / 100.0, best.address, False, ""

    majority_size = max(agrees_with) + 1 if agrees_with else 0
    if majority_size > len(successes) / 2:
        majority_idx = agrees_with.index(max(agrees_with))
        majority = successes[majority_idx]
        agreeing_scores = [
            score
            for (i, j), score in pairwise.items()
            if (i == majority_idx or j == majority_idx) and score >= AGREEMENT_THRESHOLD
        ]
        penalty = 0.85 if len(agreeing_scores) < len(successes) - 1 else 1.0
        confidence = (sum(agreeing_scores) / len(agreeing_scores) / 100.0) * penalty
        return AgreementLevel.MAJORITY, confidence, majority.address, False, ""

    # A genuine split: never silently pick one (`docs/PRINCIPLES.md` §4.3).
    detail = "; ".join(
        f"{r.provider}: {r.address.formatted}" for r in successes if r.address is not None
    )
    return AgreementLevel.SPLIT, SPLIT_CONFIDENCE, None, True, detail


def _replace(result: GeoResult, **overrides) -> GeoResult:
    return dataclasses.replace(result, **overrides)


__all__ = [
    "AGREEMENT_THRESHOLD",
    "SPLIT_CONFIDENCE",
    "geocode_with_corroboration",
]

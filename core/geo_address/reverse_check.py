"""The reverse-check phase of corroboration (`v3-deepdive-16-geo-address-api.md` §1).

**Not in the deep-dive's own §2 package layout.** The layout gives `corroboration.py` the job
of "multi-provider + multi-candidate cross-check" for the *forward* geocode; the reverse-check
capability the deep-dive's own §1 names as this API's second, genuinely distinct job (an
OCR-read vendor name cross-corroborated against the business a resolved address's own provider
data says is actually there) needs its own module rather than growing `corroboration.py` past
the file-length target (`docs/PRINCIPLES.md` §1.1, §3.1) — the same reasoning Health's own
`live_diagnostic.py`/`capability_drift.py` split already applies to that API's two distinct
responsibilities.

This is called from `corroboration.geocode_with_corroboration` — never invoked on its own by
Execution Core or Reconciliation — so both orchestrators get the identical two-capability
result from the identical one function (`docs/PRINCIPLES.md` §1.9).
"""

from __future__ import annotations

import asyncio

from rapidfuzz import fuzz

from .contracts import GeoAddress, ProviderCandidateResult
from .providers.base import GeoProvider

#: Below this token-sort-ratio (0-100), an OCR-read vendor name and the business a provider's
#: own reverse lookup reports at that address are different enough to be worth flagging as a
#: real discrepancy signal to Matching (deep-dive §1) — not a mismatch so mild it is just OCR
#: noise (a missing "Inc.", a franchise-branch suffix).
DISCREPANCY_THRESHOLD = 60.0


async def reverse_check(
    address: GeoAddress,
    vendor_name_hint: str,
    providers: tuple[GeoProvider, ...],
) -> tuple[str, bool, tuple[ProviderCandidateResult, ...]]:
    """Given a resolved address and the OCR-read vendor name, report what is actually there
    and whether the two disagree.

    Returns `(vendor_name_at_address, discrepancy, provider_results)`. Skips entirely — not a
    failure, just nothing to do — when there is no vendor name to compare against or the
    winning address carries no coordinates to reverse-look-up (§1's own scope: this is a
    cross-corroboration signal, not a requirement every geocode succeed at).

    Every provider call runs concurrently via `asyncio.gather` (§5), and a provider that fails
    or raises degrades out of the result rather than failing this check — the same
    graceful-degradation posture `corroboration.py`'s forward pass already applies
    (`docs/PRINCIPLES.md` §4.4).
    """
    if not address.has_coordinates or not vendor_name_hint.strip():
        return "", False, ()

    available = tuple(p for p in providers if p.is_available())
    if not available:
        return "", False, ()

    gathered = await asyncio.gather(
        *(
            p.reverse(address.latitude, address.longitude, country_code=address.country_code)
            for p in available
        ),
        return_exceptions=True,
    )
    results = tuple(r for r in gathered if isinstance(r, ProviderCandidateResult))

    names = [r.matched_business_name for r in results if r.ok and r.matched_business_name.strip()]
    if not names:
        return "", False, results

    # The name every other reverse-checked provider agrees with most, not simply the first —
    # the same "several signals, pick the one with the most support" instinct §3's own
    # multi-candidate axis applies to the forward pass.
    best_name = max(names, key=lambda candidate: sum(
        fuzz.token_sort_ratio(candidate, other) for other in names
    ))
    similarity = fuzz.token_sort_ratio(vendor_name_hint, best_name)
    return best_name, similarity < DISCREPANCY_THRESHOLD, results


__all__ = ["DISCREPANCY_THRESHOLD", "reverse_check"]

"""§5's resolved vendor-match corroboration policy (`v3-deepdive-15-matching-api.md` §5.1-§5.2).

**A genuine, previously-unaddressed design gap, caught directly in the deep-dive itself**:
"whether that's good enough to accept, needs Inference corroboration, or should be flagged for
review is caller policy" was never turned into a concrete policy anywhere. The default that
would naturally fall out of that placeholder — only escalate to Inference when Matching's own
confidence score is low — is the wrong default: **a deterministic fuzzy-matcher can be
confidently wrong, not just uncertain.** OCR errors don't reliably produce small edit distances
even when the correct reading is obvious to a human or an LLM — "Denny 5s" against a directory
entry "Denny's" is the deep-dive's own example. A policy that only routes low-confidence
matches to Inference would never give Inference the chance to catch that class of error at all.

**The actual mechanism**: `get_vendor_match_context` calls `two_way_match.match_vendor` — the
identical §1.9 function, never a second matching pass — and then applies the caller's own
`VendorCorroborationPolicy` purely as a *gate on whether Execution Core forwards the result into
Inference's context*, never as a filter on what Matching itself computes. Under `ALWAYS` (the
default), Matching's own confidence is irrelevant to whether Inference gets a look — which is
the actual fix, and it is structurally cheap: Inference is already being invoked for every
receipt to extract the other fields, so handing it Matching's own candidates as additional
context doesn't add a second LLM call, it adds a small amount of context to a call that was
already happening.
"""

from __future__ import annotations

from .contracts import MatchContext, MatchError, VendorCorroborationPolicy, VendorMatchContextRequest
from .errors import InvalidCorroborationPolicy, code_for, summary_for
from .metrics import MatchMetricsCollector
from .two_way_match import match_vendor


def get_vendor_match_context(
    request: VendorMatchContextRequest, *, metrics: MatchMetricsCollector | None = None
) -> MatchContext:
    """Build the context Execution Core folds into Inference's own extraction request.

    `included` is the only thing the configured policy controls:

    * `ALWAYS` — always `True`. The direct fix for the gap above: Inference reviews Matching's
      candidates regardless of how confident Matching's own top score is.
    * `NEVER` — always `False`. Trust Matching alone; available for a resource-constrained
      self-hosted install that has made a deliberate, informed tradeoff, never forced on
      anyone by default.
    * `BELOW_THRESHOLD` — `True` only when the top candidate's own score falls under
      `request.threshold` (or there is no top candidate at all, since there is nothing to
      gate). Cheaper in reasoning-token terms than `ALWAYS`, with the real, named risk of
      missing a confidently-wrong match — which is exactly why it is not the default.

    A malformed underlying request or an unrecognised policy value both surface as `error`,
    never guessed at (`docs/PRINCIPLES.md` §4.1, §4.3).
    """
    if metrics is not None:
        metrics.increment("context_calls")

    result = match_vendor(request.match_request, metrics=metrics)
    if not result.ok:
        return MatchContext(error=result.error, policy=request.policy)

    top_score = result.candidates[0].score if result.candidates else 0.0

    if request.policy is VendorCorroborationPolicy.ALWAYS:
        included = True
    elif request.policy is VendorCorroborationPolicy.NEVER:
        included = False
    elif request.policy is VendorCorroborationPolicy.BELOW_THRESHOLD:
        included = not result.candidates or top_score < request.threshold
    else:
        exc = InvalidCorroborationPolicy(str(request.policy))
        code = code_for(exc)
        return MatchContext(
            error=MatchError(code=code, detail=summary_for(code)), policy=request.policy
        )

    if metrics is not None:
        metrics.increment("context_included" if included else "context_excluded_by_policy")

    return MatchContext(
        candidates=result.candidates,
        included=included,
        policy=request.policy,
        top_score=top_score,
    )


__all__ = ["get_vendor_match_context"]

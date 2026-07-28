# V3 Deep Dive: Matching API

**Companion files:** `v3-deepdive-10-execution-core-api.md` (the primary, synchronous caller — `MATCHED` is one of its own pipeline stages) and `v3-deepdive-17-reconciliation-api.md` (the second, retroactive caller, `docs/PRINCIPLES.md` §1.9 — both found and connected during a full pipeline walkthrough), `v3-deepdive-07-tool-call-api.md` (its `vendor_tools.py` wraps this API's read side), and `v3-deepdive-26-architect-api.md` (owns the Vendor Directory data this API matches against, not this API itself).

**Status:** Fifteenth deep-dive session. `rapidfuzz` already confirmed as the fuzzy-matching library via real V2 evidence (used in the Interface deep-dive's `find_setting` tool too) — this session designs the actual vendor/TIN/address/franchise matching logic built on top of it.

---

## 1. Scope & boundary

Matching API owns the **matching/lookup logic** — fuzzy-matching an OCR-extracted vendor/address/TIN string against known-good data and returning ranked candidates. It does not:
- **own the Vendor Directory data itself** — schema, Wikidata bootstrap, aliasing, category taxonomy, and the global contribution/audit mechanism all live in Architect API's registry (file 01 #25) — Matching *consumes* that data, never maintains its own parallel copy or learns from a match itself (that's Architect's `temporal_learning`, invoked separately, not implicit in a match call).
- **decide what to do with a low-confidence match** — returns a ranked candidate list with scores; the actual policy for what happens next is resolved in §5 below, not left as an unspecified "caller policy" the way an earlier version of this document did. **This API genuinely has two legitimate callers, not one** — a real asymmetry found while tracing the pipeline, the mirror image of Geo/Address's own earlier correction (`docs/PRINCIPLES.md` §1.9): an earlier version of this line named only Reconciliation, but `MATCHED` is one of Execution Core's own synchronous per-receipt pipeline stages (`v3-deepdive-10-execution-core-api.md` §3), running before `GEOD`/`INFERRED` for every new receipt — Execution Core is the primary, synchronous caller. Reconciliation is the second, genuine caller, applying the identical underlying matching function retroactively (its own check 4.6, `v3-deepdive-17-reconciliation-api.md`, already consumes this API's own candidate-scoring output against old receipts when vendor/category data has since changed) — both callers invoke the same function, never two separate implementations, the concrete backward-carrying case §1.9 itself was generalized from.

---

## 2. Package layout

```
core/matching/
  __init__.py
  contracts.py           # MatchCandidate, MatchRequest, MatchResult, error types
  service.py                # thin gRPC service implementation
  fuzzy_match.py              # rapidfuzz-backed candidate scoring — see §3
  reverse_gazetteer.py          # the "two-way" match's reverse direction — see §4
  errors.py
  metrics.py
```

---

## 3. Forward matching — rapidfuzz, confirmed by real precedent
```python
from rapidfuzz import fuzz, process

def match_vendor(extracted: str, candidates: list[str], limit: int = 5) -> list[tuple[str, float]]:
    return process.extract(extracted, candidates, scorer=fuzz.WRatio, limit=limit)
```
`rapidfuzz` is a C/Cython extension — already GIL-released during the actual comparison (file 02's Concurrency Model table), so plain threading already achieves real parallelism for a bulk matching sweep across many receipts without needing multiprocessing or free-threading considerations. `fuzz.WRatio` (a weighted combination of several ratio functions) is a reasonable default scorer for vendor-name matching specifically, since it handles partial/reordered-token matches better than a plain Levenshtein ratio alone — worth bench-validating against real OCR output rather than assumed optimal, consistent with this project's "reasoned, then measured" discipline applied everywhere else.

---

## 4. The two-way match — forward candidate lookup plus reverse gazetteer scan
File 01's own framing: not just "does this extracted string match a known vendor" (forward), but also "does any *known* vendor name/alias appear anywhere in the full raw OCR text" (reverse) — catching cases where the primary field-extraction missed or mangled the vendor line, but the vendor's actual name still appears somewhere legible in the receipt's raw text.
```python
def reverse_gazetteer_scan(raw_ocr_text: str, known_names: list[str], plausibility_window: int = 500) -> list[MatchCandidate]:
    """Scans known vendor names/aliases against the full raw OCR text,
    not the single extracted vendor field — scoped to a
    contextually-plausible subset (e.g. the first N characters, where a
    receipt's vendor line typically lives) rather than the full known-
    vendor universe against the full text, to bound cost. The exact
    scoping heuristic is a real design detail worth bench-tuning against
    actual receipt layouts, not assumed correct from a single guess."""
```
This is explicitly named in file 01 as a cost-bounding requirement, not an unconstrained scan — worth stating plainly why: the known-vendor universe (via Architect's Wikidata-seeded directory) could be large, and scanning every name against every character of every receipt's raw text without bounding scope would be a real, avoidable performance problem.

---

## 5. Vendor-match corroboration policy — resolved, a real gap this document previously left unspecified

**A genuine, previously-unaddressed design gap, caught directly**: "whether that's good enough to accept, needs Inference corroboration, or should be flagged for review is caller policy" was never actually turned into a concrete policy anywhere — it sat as an unresolved placeholder. The default assumption that would naturally fall out of that placeholder — only escalate to Inference when Matching's own confidence score is low — is the wrong default, and worth being explicit about why: **a deterministic fuzzy-matcher can be confidently wrong, not just uncertain.** OCR errors don't reliably produce small edit distances even when the correct reading is obvious to a human or an LLM — "Denny 5s" against a directory entry "Denny's" is a real example of exactly this: character-level fuzzy scoring may not rate that pair as a strong match at all (or worse, may confidently match something else entirely), while an LLM's own world knowledge recognizes the correction immediately, well before any vendor-specific corroboration logic even runs. A policy that only routes low-confidence matches to Inference would never give Inference the chance to catch this class of error at all.

### 5.1 The actual mechanism — Matching's candidates are always Inference's input, never gated behind a confidence check
```python
async def get_vendor_match_context(receipt_id: str) -> MatchContext:
    """Called by Execution Core as part of assembling Inference's own
    extraction request for the INFERRED stage — not a separate,
    additional LLM call. Matching's own ranked candidate list (with
    scores) is included in Inference's existing context alongside the
    raw OCR text, every time, regardless of how confident Matching's
    own top candidate is. Inference's own structured extraction output
    is what becomes the final, canonical vendor identity — Matching's
    candidates are corroborating input to that decision, never a gate
    that decides whether Inference gets a say at all."""
```
This is the actual fix, and it's structurally cheap: Inference is already being invoked for every receipt to extract the other fields (date, amount, line items) — giving it Matching's own candidates as additional context doesn't add a second LLM call, it adds a small amount of context to a call that was already happening.

### 5.2 A real, owner-configurable setting — the cost/thoroughness tradeoff stated honestly, not hidden
```python
class VendorCorroborationPolicy(str, Enum):
    ALWAYS = "always"                            # Inference always reviews Matching's candidates, can override regardless of Matching's own confidence — the default, and the direct fix for the gap above
    BELOW_THRESHOLD = "below_threshold"             # Inference only reviews when Matching's own top score falls under a configurable bar — cheaper in reasoning-token terms, real risk of missing a confidently-wrong match
    NEVER = "never"                                   # trust Matching alone — fastest and cheapest, not recommended, available for a resource-constrained self-hosted install that's made a deliberate tradeoff
```
`ALWAYS` is the default given the real failure mode this section exists to close. `BELOW_THRESHOLD` and `NEVER` stay available — not every self-hosted install runs on hardware where the marginal context cost of always-including Matching's candidates is negligible, and an owner who's made a deliberate, informed tradeoff should be able to choose the cheaper option rather than have `ALWAYS` forced on them unconditionally.

---

## 6. Asyncio and profiling
Matching's own compute (`rapidfuzz` calls) is native/GIL-released — real parallelism via plain threading already, no `run_in_executor` dispatch needed the way blocking-native-call APIs elsewhere in this project require, since `rapidfuzz` itself doesn't block the interpreter the way a subprocess call or an ONNX Runtime session does. The surrounding orchestration (fetching candidate lists from Architect's registry, returning results) is ordinary async I/O. No compute-bound pure-Python hot path exists here worth a free-threading discussion beyond what's already stated.

---

## 7. gRPC surface

```protobuf
service MatchingService {
  rpc MatchVendor(MatchRequest) returns (MatchResponse);
  rpc ReverseGazetteerScan(GazetteerScanRequest) returns (MatchResponse);
}

message MatchResponse {
  repeated MatchCandidate candidates = 1;   // ranked, highest score first
}

message MatchCandidate {
  string canonical_name = 1;
  float score = 2;
  string source = 3;    // "forward" | "reverse_gazetteer"
}
```

---

## 8. Testing hooks
- **Confidently-wrong-match regression test — the concrete validation of §5's own reason for existing**: a case constructed so Matching's own top candidate is high-confidence but actually wrong (or matches nothing at all) against ground truth, confirming that under the `ALWAYS` policy, Inference's own final vendor decision still correctly overrides it — proof this isn't just a documented intention.
- **`BELOW_THRESHOLD`/`NEVER` policy tests**: confirm each policy actually gates Inference's own review the way its name claims — `BELOW_THRESHOLD` skipping corroboration above the configured bar, `NEVER` never including Matching's candidates in Inference's context at all.
- **Scorer bench comparison**: `WRatio` vs. alternative rapidfuzz scorers against a labeled real-vendor-name sample, resolving §3's "worth bench-validating" note with actual data rather than leaving `WRatio` as an unverified default indefinitely.
- **Reverse-scan cost bench**: confirms the plausibility-window scoping actually keeps scan cost bounded as the known-vendor universe grows, not just at today's directory size.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Reverse-scan plausibility-window heuristic** (§4): the current placeholder scoping approach ships as the default — reasoned, not arbitrary; bench validation against real receipt layouts can tune it later, not a blocking gap.
- **Franchise-vs-franchiser matching, resolved now that Architect's directory schema actually exists.** temporal_learning's own Corporation/Branch/Franchiser model (`v3-deepdive-40-temporal-learning.md` §4) settles the data shape this was waiting on: a receipt's OCR'd franchiser text (the local operator's own name/TIN, distinct from the parent corporation's) matches against the Franchiser list independently of the Corporation/vendor match itself — two separate fuzzy-match passes, not one combined heuristic, since a wrong franchiser match shouldn't be able to drag down confidence in an otherwise-correct vendor match or vice versa. A `Branch.franchiser_id` hit from this pass corroborates (or flags a mismatch against) whatever the branch's own existing franchiser link already says, the same corroboration-not-override discipline every other check in this project follows.
- **V2's hard-learned fuzzy-matching pitfalls, given real, concrete safeguards rather than left as an acknowledged risk list.** Four specific, addressable failure modes: **case sensitivity** — normalize both sides (query and candidate) to a consistent case before scoring, never compare raw-cased strings; **over-eager collapsing of distinct names** — a minimum edit-distance floor relative to string length, so two genuinely different short names don't score as a false match just because short strings collapse easily under naive ratio-based scoring; **generic words causing false positives** — a stopword-adjacent list of category-generic terms ("store," "shop," "restaurant") excluded from the matched-token contribution to a score, so two unrelated vendors that both happen to contain "Store" don't score artificially high; **needing multiple sightings before trusting a correction** — directly ties into temporal_learning's own confidence-accumulation model (its deep-dive §5), where a single low-confidence local observation never overrides an existing higher-confidence global fact on its own. All four are now real, concrete design requirements for `fuzzy_match.py`/the scorer itself, not just a list of risks to remember.
